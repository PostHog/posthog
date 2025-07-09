"""
Real-time Behavioral Cohort Event Processor

This module implements the Kafka consumer that processes events in real-time
to increment behavioral cohort counters as described in the RFC.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

from django.conf import settings
from django.utils import timezone

from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.parser import parse_expr
from posthog.hogvm.python.execute import execute_bytecode
from posthog.models.cohort.behavioral_counter import BehavioralCounterManager
from posthog.models.cohort.cohort import Cohort
from posthog.models.person.person import Person
from posthog.models.team.team import Team
from posthog.redis import get_client


logger = logging.getLogger(__name__)


class BehavioralCohortProcessor:
    """
    Processes events in real-time to maintain behavioral cohort counters.
    
    This processor:
    1. Loads active behavioral cohorts for a team
    2. Evaluates events against compiled filter bytecode
    3. Increments counters for matching events
    4. Handles person ID resolution and timezone conversion
    """
    
    def __init__(self):
        self.counter_manager = BehavioralCounterManager()
        self.redis_client = get_client()
        self._team_cache = {}  # Cache for team objects
        self._cohort_cache = {}  # Cache for active cohorts
        self._person_cache = {}  # Cache for person lookups
        
    def process_event(self, event_data: Dict) -> None:
        """
        Process a single event and update behavioral counters.
        
        Args:
            event_data: Event data from Kafka
        """
        try:
            # Extract key fields
            team_id = event_data.get("team_id")
            person_id = event_data.get("person_id")
            distinct_id = event_data.get("distinct_id")
            timestamp = event_data.get("timestamp")
            event_name = event_data.get("event")
            properties = event_data.get("properties", {})
            
            if not all([team_id, timestamp, event_name]):
                logger.warning(f"Missing required fields in event: {event_data}")
                return
            
            # Get team and convert timestamp to team timezone
            team = self._get_team(team_id)
            if not team:
                return
                
            event_datetime = self._convert_to_team_timezone(timestamp, team)
            
            # Resolve person ID if needed
            if not person_id and distinct_id:
                person_id = self._resolve_person_id(team_id, distinct_id)
            
            if not person_id:
                logger.debug(f"Could not resolve person for distinct_id: {distinct_id}")
                return
            
            # Get active behavioral cohorts for this team
            cohorts = self._get_active_behavioral_cohorts(team_id)
            
            # Process each cohort
            for cohort in cohorts:
                self._process_cohort_event(cohort, event_data, person_id, event_datetime)
                
        except Exception as e:
            logger.error(f"Error processing event: {e}", exc_info=True)
    
    def _process_cohort_event(
        self, 
        cohort: Cohort, 
        event_data: Dict, 
        person_id: int, 
        event_datetime: datetime
    ) -> None:
        """
        Process an event against a specific cohort's filters.
        
        Args:
            cohort: Cohort to evaluate
            event_data: Event data
            person_id: Resolved person ID
            event_datetime: Event timestamp in team timezone
        """
        try:
            # Get cached bytecode for this cohort
            filter_hash = self.counter_manager.compile_and_cache_filters(
                cohort.team_id, 
                cohort.filters
            )
            
            bytecode = self.counter_manager.get_cached_bytecode(cohort.team_id, filter_hash)
            if not bytecode:
                logger.warning(f"No bytecode found for cohort {cohort.id}")
                return
            
            # Prepare execution context
            execution_context = {
                "event": event_data.get("event"),
                "properties": event_data.get("properties", {}),
                "person_properties": self._get_person_properties(person_id),
                "timestamp": event_datetime.isoformat(),
                "distinct_id": event_data.get("distinct_id"),
                "team_id": cohort.team_id,
                "person_id": person_id
            }
            
            # Execute bytecode against event
            try:
                result = execute_bytecode(
                    bytecode,
                    globals=execution_context,
                    timeout=timedelta(seconds=1)
                )
                
                # If filters match, increment counter
                if result:
                    self.counter_manager.increment_counter(
                        cohort.team_id,
                        filter_hash,
                        person_id,
                        event_datetime
                    )
                    
                    logger.debug(
                        f"Incremented counter for cohort {cohort.id}, "
                        f"person {person_id}, date {event_datetime.date()}"
                    )
                    
            except Exception as e:
                logger.error(f"Error executing bytecode for cohort {cohort.id}: {e}")
                
        except Exception as e:
            logger.error(f"Error processing cohort event: {e}", exc_info=True)
    
    def _get_team(self, team_id: int) -> Optional[Team]:
        """Get team object with caching."""
        if team_id not in self._team_cache:
            try:
                team = Team.objects.get(id=team_id)
                self._team_cache[team_id] = team
            except Team.DoesNotExist:
                logger.warning(f"Team {team_id} not found")
                return None
        
        return self._team_cache[team_id]
    
    def _convert_to_team_timezone(self, timestamp: str, team: Team) -> datetime:
        """Convert timestamp to team timezone."""
        try:
            # Parse timestamp (assume ISO format)
            if isinstance(timestamp, str):
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            
            # Convert to team timezone if configured
            if team.timezone:
                try:
                    import pytz
                    team_tz = pytz.timezone(team.timezone)
                    dt = dt.astimezone(team_tz)
                except Exception:
                    logger.warning(f"Invalid timezone {team.timezone} for team {team.id}")
            
            return dt
            
        except Exception as e:
            logger.error(f"Error converting timestamp: {e}")
            return timezone.now()
    
    def _resolve_person_id(self, team_id: int, distinct_id: str) -> Optional[int]:
        """Resolve person ID from distinct ID."""
        cache_key = f"{team_id}:{distinct_id}"
        
        if cache_key not in self._person_cache:
            try:
                from posthog.models.person.person import PersonDistinctId
                person_distinct_id = PersonDistinctId.objects.select_related('person').get(
                    distinct_id=distinct_id,
                    team_id=team_id
                )
                self._person_cache[cache_key] = person_distinct_id.person.id
            except PersonDistinctId.DoesNotExist:
                logger.debug(f"Person not found for distinct_id {distinct_id}")
                return None
        
        return self._person_cache[cache_key]
    
    def _get_person_properties(self, person_id: int) -> Dict:
        """Get person properties for execution context."""
        try:
            person = Person.objects.get(id=person_id)
            return person.properties or {}
        except Person.DoesNotExist:
            return {}
    
    def _get_active_behavioral_cohorts(self, team_id: int) -> List[Cohort]:
        """Get active behavioral cohorts for a team with caching."""
        cache_key = f"behavioral_cohorts:{team_id}"
        
        # Check Redis cache first
        cached_cohorts = self.redis_client.get(cache_key)
        if cached_cohorts:
            try:
                cohort_ids = json.loads(cached_cohorts)
                return [self._get_cohort(cohort_id) for cohort_id in cohort_ids 
                       if self._get_cohort(cohort_id)]
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Query database for behavioral cohorts
        cohorts = list(
            Cohort.objects.filter(
                team_id=team_id,
                is_calculating=False,
                deleted=False
            ).exclude(
                is_static=True
            ).filter(
                filters__has_keys=["properties"]
            )
        )
        
        # Filter for behavioral cohorts
        behavioral_cohorts = []
        for cohort in cohorts:
            if self._is_behavioral_cohort(cohort):
                behavioral_cohorts.append(cohort)
        
        # Cache cohort IDs for 5 minutes
        cohort_ids = [cohort.id for cohort in behavioral_cohorts]
        self.redis_client.setex(cache_key, 300, json.dumps(cohort_ids))
        
        return behavioral_cohorts
    
    def _get_cohort(self, cohort_id: int) -> Optional[Cohort]:
        """Get cohort with caching."""
        if cohort_id not in self._cohort_cache:
            try:
                cohort = Cohort.objects.get(id=cohort_id)
                self._cohort_cache[cohort_id] = cohort
            except Cohort.DoesNotExist:
                return None
        
        return self._cohort_cache[cohort_id]
    
    def _is_behavioral_cohort(self, cohort: Cohort) -> bool:
        """Check if cohort has behavioral filters."""
        try:
            filters = cohort.filters
            if not filters or "properties" not in filters:
                return False
            
            properties = filters["properties"]
            if not isinstance(properties, dict) or "values" not in properties:
                return False
            
            # Check if any property is behavioral
            for prop in properties.get("values", []):
                if isinstance(prop, dict) and prop.get("type") == "behavioral":
                    return True
            
            return False
            
        except Exception:
            return False
    
    def process_batch(self, events: List[Dict]) -> None:
        """
        Process a batch of events efficiently.
        
        Args:
            events: List of event data dictionaries
        """
        if not events:
            return
        
        # Group events by team_id for efficient processing
        events_by_team = {}
        for event in events:
            team_id = event.get("team_id")
            if team_id:
                if team_id not in events_by_team:
                    events_by_team[team_id] = []
                events_by_team[team_id].append(event)
        
        # Process each team's events
        for team_id, team_events in events_by_team.items():
            self._process_team_events(team_id, team_events)
    
    def _process_team_events(self, team_id: int, events: List[Dict]) -> None:
        """Process events for a specific team."""
        # Pre-load cohorts for this team
        cohorts = self._get_active_behavioral_cohorts(team_id)
        if not cohorts:
            return
        
        # Process each event
        for event in events:
            self.process_event(event)
    
    def clear_cache(self) -> None:
        """Clear internal caches."""
        self._team_cache.clear()
        self._cohort_cache.clear()
        self._person_cache.clear()


class BehavioralCohortKafkaConsumer:
    """
    Kafka consumer for behavioral cohort events.
    
    This would integrate with the existing Kafka infrastructure
    to consume events and process them for behavioral counting.
    """
    
    def __init__(self, topic: str = "behavioral_cohort_events"):
        self.topic = topic
        self.processor = BehavioralCohortProcessor()
        
    def consume_events(self):
        """
        Main consumer loop (placeholder for Kafka integration).
        
        This would integrate with the existing Kafka consumer pattern
        used in the plugin-server architecture.
        """
        # This would use the existing Kafka consumer infrastructure
        # from plugin-server/src/main/ingestion-queues/kafka-queue.ts
        pass
    
    def process_message(self, message: Dict) -> None:
        """Process a single Kafka message."""
        try:
            self.processor.process_event(message)
        except Exception as e:
            logger.error(f"Error processing Kafka message: {e}", exc_info=True)
    
    def process_batch(self, messages: List[Dict]) -> None:
        """Process a batch of Kafka messages."""
        try:
            events = [msg for msg in messages if msg]
            self.processor.process_batch(events)
        except Exception as e:
            logger.error(f"Error processing batch: {e}", exc_info=True)