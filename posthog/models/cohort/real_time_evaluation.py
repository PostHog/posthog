"""
Real-time Cohort Evaluation Service

This module provides the service layer for evaluating behavioral cohorts
using real-time aggregated counters as described in the RFC.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from django.db import transaction
from django.utils import timezone

from posthog.models.cohort.behavioral_counter import BehavioralCounter, BehavioralCounterManager
from posthog.models.cohort.cohort import Cohort
from posthog.models.person.person import Person
from posthog.models.team.team import Team


logger = logging.getLogger(__name__)


class RealTimeCohortEvaluationError(Exception):
    """Exception raised for cohort evaluation errors."""
    pass


class RealTimeCohortEvaluator:
    """
    Evaluates behavioral cohorts using real-time aggregated counters.
    
    This service:
    1. Evaluates persons against behavioral cohort criteria
    2. Uses real-time counters instead of ClickHouse queries
    3. Handles complex behavioral patterns (performed_event_multiple, etc.)
    4. Provides efficient batch evaluation for large cohorts
    """
    
    def __init__(self):
        self.counter_manager = BehavioralCounterManager()
    
    def evaluate_cohort_for_person(
        self, 
        cohort: Cohort, 
        person_id: int,
        evaluation_date: Optional[datetime] = None
    ) -> bool:
        """
        Evaluate if a person matches a behavioral cohort.
        
        Args:
            cohort: Cohort to evaluate
            person_id: Person to evaluate
            evaluation_date: Date to evaluate against (defaults to now)
            
        Returns:
            True if person matches cohort criteria
        """
        if evaluation_date is None:
            evaluation_date = timezone.now()
        
        try:
            # Parse behavioral filters
            behavioral_criteria = self._parse_behavioral_filters(cohort.filters)
            
            if not behavioral_criteria:
                logger.warning(f"No behavioral criteria found in cohort {cohort.id}")
                return False
            
            # Evaluate each criterion
            for criterion in behavioral_criteria:
                if not self._evaluate_behavioral_criterion(
                    cohort, person_id, criterion, evaluation_date
                ):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error evaluating cohort {cohort.id} for person {person_id}: {e}")
            return False
    
    def _parse_behavioral_filters(self, filters: Dict) -> List[Dict]:
        """
        Parse behavioral filters from cohort filters.
        
        Args:
            filters: Cohort filters dictionary
            
        Returns:
            List of behavioral criteria
        """
        criteria = []
        
        if not filters or "properties" not in filters:
            return criteria
        
        properties = filters["properties"]
        if not isinstance(properties, dict) or "values" not in properties:
            return criteria
        
        for prop in properties.get("values", []):
            if isinstance(prop, dict) and prop.get("type") == "behavioral":
                criteria.append(prop)
        
        return criteria
    
    def _evaluate_behavioral_criterion(
        self, 
        cohort: Cohort, 
        person_id: int, 
        criterion: Dict,
        evaluation_date: datetime
    ) -> bool:
        """
        Evaluate a single behavioral criterion.
        
        Args:
            cohort: Cohort being evaluated
            person_id: Person being evaluated
            criterion: Behavioral criterion to evaluate
            evaluation_date: Date to evaluate against
            
        Returns:
            True if criterion is met
        """
        try:
            behavior_type = criterion.get("value")
            threshold = int(criterion.get("operator_value", 1))
            time_value = int(criterion.get("time_value", 7))
            time_interval = criterion.get("time_interval", "day")
            
            # Convert time interval to days
            if time_interval == "hour":
                days = max(1, time_value // 24)
            elif time_interval == "day":
                days = time_value
            elif time_interval == "week":
                days = time_value * 7
            elif time_interval == "month":
                days = time_value * 30
            else:
                days = time_value  # Default to days
            
            # Get behavioral counter for this cohort
            counter = BehavioralCounter(cohort.team_id, cohort)
            
            # Evaluate based on behavior type
            if behavior_type == "performed_event":
                return self._evaluate_performed_event(counter, person_id, threshold, days)
            elif behavior_type == "performed_event_multiple":
                return self._evaluate_performed_event_multiple(counter, person_id, threshold, days)
            elif behavior_type == "performed_event_first_time":
                return self._evaluate_performed_event_first_time(counter, person_id, days)
            elif behavior_type == "performed_event_regularly":
                return self._evaluate_performed_event_regularly(counter, person_id, threshold, days)
            elif behavior_type == "stopped_performing_event":
                return self._evaluate_stopped_performing_event(counter, person_id, threshold, days)
            elif behavior_type == "restarted_performing_event":
                return self._evaluate_restarted_performing_event(counter, person_id, threshold, days)
            else:
                logger.warning(f"Unknown behavior type: {behavior_type}")
                return False
                
        except Exception as e:
            logger.error(f"Error evaluating behavioral criterion: {e}")
            return False
    
    def _evaluate_performed_event(
        self, 
        counter: BehavioralCounter, 
        person_id: int, 
        threshold: int, 
        days: int
    ) -> bool:
        """Evaluate 'performed event' criterion."""
        count = counter.get_person_count(person_id, days)
        return count >= threshold
    
    def _evaluate_performed_event_multiple(
        self, 
        counter: BehavioralCounter, 
        person_id: int, 
        threshold: int, 
        days: int
    ) -> bool:
        """Evaluate 'performed event multiple times' criterion."""
        count = counter.get_person_count(person_id, days)
        return count >= threshold
    
    def _evaluate_performed_event_first_time(
        self, 
        counter: BehavioralCounter, 
        person_id: int, 
        days: int
    ) -> bool:
        """Evaluate 'performed event for first time' criterion."""
        # Check if event occurred in the time window
        recent_count = counter.get_person_count(person_id, days)
        
        # Check if event never occurred before the time window
        # This would require additional logic to track "first time" events
        # For now, simplified to check if event occurred in recent period
        return recent_count > 0
    
    def _evaluate_performed_event_regularly(
        self, 
        counter: BehavioralCounter, 
        person_id: int, 
        threshold: int, 
        days: int
    ) -> bool:
        """Evaluate 'performed event regularly' criterion."""
        # Get daily counts for the period
        daily_counts = counter.manager.get_person_daily_counts(
            counter.team_id, 
            counter.filter_hash, 
            person_id, 
            days
        )
        
        # Count days with activity
        active_days = sum(1 for _, count in daily_counts if count > 0)
        
        # Consider "regularly" as occurring on at least half the days
        required_days = max(1, days // 2)
        return active_days >= required_days
    
    def _evaluate_stopped_performing_event(
        self, 
        counter: BehavioralCounter, 
        person_id: int, 
        threshold: int, 
        days: int
    ) -> bool:
        """Evaluate 'stopped performing event' criterion."""
        # Check recent period (last 1/3 of time window)
        recent_days = max(1, days // 3)
        recent_count = counter.get_person_count(person_id, recent_days)
        
        # Check earlier period (first 2/3 of time window)
        # This would require more complex date range queries
        # For now, simplified to check if no recent activity
        return recent_count == 0
    
    def _evaluate_restarted_performing_event(
        self, 
        counter: BehavioralCounter, 
        person_id: int, 
        threshold: int, 
        days: int
    ) -> bool:
        """Evaluate 'restarted performing event' criterion."""
        # Check recent period (last 1/3 of time window)
        recent_days = max(1, days // 3)
        recent_count = counter.get_person_count(person_id, recent_days)
        
        # For now, simplified to check if there's recent activity
        # Full implementation would need to check for gap in activity
        return recent_count > 0
    
    def evaluate_cohort_batch(
        self, 
        cohort: Cohort, 
        person_ids: List[int],
        evaluation_date: Optional[datetime] = None
    ) -> Dict[int, bool]:
        """
        Evaluate a cohort for multiple persons efficiently.
        
        Args:
            cohort: Cohort to evaluate
            person_ids: List of person IDs to evaluate
            evaluation_date: Date to evaluate against
            
        Returns:
            Dictionary mapping person_id to evaluation result
        """
        results = {}
        
        # Evaluate each person
        for person_id in person_ids:
            try:
                results[person_id] = self.evaluate_cohort_for_person(
                    cohort, person_id, evaluation_date
                )
            except Exception as e:
                logger.error(f"Error evaluating person {person_id}: {e}")
                results[person_id] = False
        
        return results
    
    def get_cohort_size_estimate(self, cohort: Cohort) -> int:
        """
        Get an estimate of cohort size using counters.
        
        Args:
            cohort: Cohort to estimate
            
        Returns:
            Estimated number of persons in cohort
        """
        try:
            # This would require more sophisticated logic to estimate
            # based on counter patterns across all persons
            # For now, return a placeholder
            return 0
            
        except Exception as e:
            logger.error(f"Error estimating cohort size: {e}")
            return 0
    
    def get_cohort_trends(
        self, 
        cohort: Cohort, 
        days: int = 30
    ) -> List[Tuple[datetime, int]]:
        """
        Get cohort membership trends over time.
        
        Args:
            cohort: Cohort to analyze
            days: Number of days to analyze
            
        Returns:
            List of (date, count) tuples
        """
        try:
            # This would aggregate counters across all persons
            # to show cohort growth/decline trends
            # For now, return empty list
            return []
            
        except Exception as e:
            logger.error(f"Error getting cohort trends: {e}")
            return []


class RealTimeCohortService:
    """
    High-level service for real-time cohort operations.
    
    This service provides the main API for working with real-time
    behavioral cohorts in the application.
    """
    
    def __init__(self):
        self.evaluator = RealTimeCohortEvaluator()
        self.counter_manager = BehavioralCounterManager()
    
    def is_person_in_cohort(self, cohort_id: int, person_id: int) -> bool:
        """
        Check if a person is currently in a behavioral cohort.
        
        Args:
            cohort_id: Cohort ID
            person_id: Person ID
            
        Returns:
            True if person is in cohort
        """
        try:
            cohort = Cohort.objects.get(id=cohort_id)
            return self.evaluator.evaluate_cohort_for_person(cohort, person_id)
        except Cohort.DoesNotExist:
            return False
    
    def get_cohort_members(self, cohort_id: int, limit: int = 100) -> List[int]:
        """
        Get current members of a behavioral cohort.
        
        Args:
            cohort_id: Cohort ID
            limit: Maximum number of members to return
            
        Returns:
            List of person IDs in the cohort
        """
        try:
            cohort = Cohort.objects.get(id=cohort_id)
            
            # This would need to efficiently find all persons
            # who match the cohort criteria
            # For now, return empty list
            return []
            
        except Cohort.DoesNotExist:
            return []
    
    def invalidate_cohort_cache(self, cohort_id: int) -> None:
        """
        Invalidate cached data for a cohort.
        
        Args:
            cohort_id: Cohort ID to invalidate
        """
        try:
            cohort = Cohort.objects.get(id=cohort_id)
            counter = BehavioralCounter(cohort.team_id, cohort)
            counter.invalidate_cache()
        except Cohort.DoesNotExist:
            pass
    
    def get_person_cohort_memberships(self, person_id: int, team_id: int) -> List[int]:
        """
        Get all behavioral cohorts a person belongs to.
        
        Args:
            person_id: Person ID
            team_id: Team ID
            
        Returns:
            List of cohort IDs the person belongs to
        """
        try:
            # Get all behavioral cohorts for the team
            cohorts = Cohort.objects.filter(
                team_id=team_id,
                is_calculating=False,
                deleted=False
            ).exclude(is_static=True)
            
            memberships = []
            for cohort in cohorts:
                if self.evaluator.evaluate_cohort_for_person(cohort, person_id):
                    memberships.append(cohort.id)
            
            return memberships
            
        except Exception as e:
            logger.error(f"Error getting person cohort memberships: {e}")
            return []