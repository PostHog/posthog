"""
Behavioral Counter Models for Real-time Cohort Counting

This module implements the data structures and storage layer for real-time
behavioral cohort counting as described in the RFC.
"""

import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from redis import Redis

from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.parser import parse_expr
from posthog.models.cohort.cohort import Cohort
from posthog.models.filters.filter import Filter
from posthog.models.property.property import PropertyGroup
from posthog.redis import get_client


class BehavioralCounterError(Exception):
    """Exception raised for behavioral counter operations."""
    pass


class BehavioralCounterManager:
    """
    Manages real-time behavioral counters using Redis for storage.
    
    Implements the RFC's proposal for team_id:bytecode_hash:person_id:yyyy-mm-dd
    counter structure with bytecode caching.
    """
    
    def __init__(self, redis_client: Optional[Redis] = None):
        self.redis_client = redis_client or get_client()
        self.cache_prefix = "behavioral_counter"
        self.bytecode_cache_prefix = "filter_bytecode"
        self.metadata_cache_prefix = "filter_metadata"
        
    def compile_and_cache_filters(self, team_id: int, filters: Dict) -> str:
        """
        Compile behavioral filters to bytecode and cache with hash.
        
        Args:
            team_id: Team identifier
            filters: Behavioral filter dictionary
            
        Returns:
            Hash of the compiled bytecode
        """
        # Create hash of filters for caching
        filter_str = str(sorted(filters.items()))
        filter_hash = hashlib.sha256(f"{team_id}:{filter_str}".encode()).hexdigest()[:16]
        
        # Check if already cached
        bytecode_key = f"{self.bytecode_cache_prefix}:{team_id}:{filter_hash}"
        cached_bytecode = self.redis_client.get(bytecode_key)
        
        if cached_bytecode:
            return filter_hash
            
        try:
            # Convert filters to PropertyGroup for compilation
            property_group = PropertyGroup.from_dict(filters)
            
            # Compile to HogQL expression and then to bytecode
            hogql_expr = property_group.to_hogql()
            compiled_bytecode = create_bytecode(parse_expr(hogql_expr))
            
            # Cache bytecode and metadata
            self.redis_client.setex(
                bytecode_key,
                timedelta(days=30),  # 30 day TTL
                compiled_bytecode.bytecode
            )
            
            metadata_key = f"{self.metadata_cache_prefix}:{team_id}:{filter_hash}"
            self.redis_client.setex(
                metadata_key,
                timedelta(days=30),
                {
                    "original_filters": filters,
                    "compiled_at": timezone.now().isoformat(),
                    "team_id": team_id
                }
            )
            
            return filter_hash
            
        except Exception as e:
            raise BehavioralCounterError(f"Failed to compile filters: {e}")
    
    def increment_counter(
        self, 
        team_id: int, 
        filter_hash: str, 
        person_id: int, 
        date: datetime,
        increment: int = 1
    ) -> int:
        """
        Increment behavioral counter for a specific person and date.
        
        Args:
            team_id: Team identifier
            filter_hash: Hash of the compiled filters
            person_id: Person identifier
            date: Date for the counter
            increment: Amount to increment by
            
        Returns:
            New counter value
        """
        date_str = date.strftime("%Y-%m-%d")
        counter_key = f"{self.cache_prefix}:{team_id}:{filter_hash}:{person_id}:{date_str}"
        
        # Increment counter with 90 day TTL
        pipeline = self.redis_client.pipeline()
        pipeline.incr(counter_key, increment)
        pipeline.expire(counter_key, timedelta(days=90))
        results = pipeline.execute()
        
        return results[0]
    
    def get_counter_value(
        self, 
        team_id: int, 
        filter_hash: str, 
        person_id: int, 
        date: datetime
    ) -> int:
        """
        Get current counter value for a person and date.
        
        Args:
            team_id: Team identifier
            filter_hash: Hash of the compiled filters
            person_id: Person identifier
            date: Date for the counter
            
        Returns:
            Current counter value
        """
        date_str = date.strftime("%Y-%m-%d")
        counter_key = f"{self.cache_prefix}:{team_id}:{filter_hash}:{person_id}:{date_str}"
        
        value = self.redis_client.get(counter_key)
        return int(value) if value else 0
    
    def get_aggregated_count(
        self, 
        team_id: int, 
        filter_hash: str, 
        person_id: int, 
        start_date: datetime,
        end_date: datetime
    ) -> int:
        """
        Get aggregated count for a person across a date range.
        
        Args:
            team_id: Team identifier
            filter_hash: Hash of the compiled filters
            person_id: Person identifier
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            
        Returns:
            Aggregated count across the date range
        """
        current_date = start_date
        counter_keys = []
        
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            counter_key = f"{self.cache_prefix}:{team_id}:{filter_hash}:{person_id}:{date_str}"
            counter_keys.append(counter_key)
            current_date += timedelta(days=1)
        
        if not counter_keys:
            return 0
            
        # Use pipeline for efficient multi-get
        pipeline = self.redis_client.pipeline()
        for key in counter_keys:
            pipeline.get(key)
        values = pipeline.execute()
        
        # Sum all non-None values
        total = sum(int(value) for value in values if value is not None)
        return total
    
    def get_cached_bytecode(self, team_id: int, filter_hash: str) -> Optional[bytes]:
        """
        Retrieve cached bytecode for a filter hash.
        
        Args:
            team_id: Team identifier
            filter_hash: Hash of the compiled filters
            
        Returns:
            Cached bytecode or None if not found
        """
        bytecode_key = f"{self.bytecode_cache_prefix}:{team_id}:{filter_hash}"
        return self.redis_client.get(bytecode_key)
    
    def invalidate_filter_cache(self, team_id: int, filter_hash: str) -> None:
        """
        Invalidate cached bytecode and metadata for a filter.
        
        Args:
            team_id: Team identifier
            filter_hash: Hash of the compiled filters
        """
        bytecode_key = f"{self.bytecode_cache_prefix}:{team_id}:{filter_hash}"
        metadata_key = f"{self.metadata_cache_prefix}:{team_id}:{filter_hash}"
        
        pipeline = self.redis_client.pipeline()
        pipeline.delete(bytecode_key)
        pipeline.delete(metadata_key)
        pipeline.execute()
    
    def get_person_daily_counts(
        self, 
        team_id: int, 
        filter_hash: str, 
        person_id: int, 
        days: int = 30
    ) -> List[Tuple[datetime, int]]:
        """
        Get daily counts for a person over the last N days.
        
        Args:
            team_id: Team identifier
            filter_hash: Hash of the compiled filters
            person_id: Person identifier
            days: Number of days to look back
            
        Returns:
            List of (date, count) tuples
        """
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days-1)
        
        current_date = start_date
        counter_keys = []
        dates = []
        
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            counter_key = f"{self.cache_prefix}:{team_id}:{filter_hash}:{person_id}:{date_str}"
            counter_keys.append(counter_key)
            dates.append(current_date)
            current_date += timedelta(days=1)
        
        # Get all values at once
        pipeline = self.redis_client.pipeline()
        for key in counter_keys:
            pipeline.get(key)
        values = pipeline.execute()
        
        # Combine dates with counts
        results = []
        for date, value in zip(dates, values):
            count = int(value) if value is not None else 0
            results.append((datetime.combine(date, datetime.min.time()), count))
        
        return results


class BehavioralCounter:
    """
    Model-like interface for behavioral counters.
    
    Provides a Django-like API for working with behavioral counters
    while using Redis as the storage backend.
    """
    
    def __init__(self, team_id: int, cohort: Cohort):
        self.team_id = team_id
        self.cohort = cohort
        self.manager = BehavioralCounterManager()
        self._filter_hash = None
        
    @property
    def filter_hash(self) -> str:
        """Get or create filter hash for this cohort."""
        if self._filter_hash is None:
            self._filter_hash = self.manager.compile_and_cache_filters(
                self.team_id, 
                self.cohort.filters
            )
        return self._filter_hash
    
    def increment_for_person(self, person_id: int, date: datetime, increment: int = 1) -> int:
        """Increment counter for a specific person and date."""
        return self.manager.increment_counter(
            self.team_id,
            self.filter_hash,
            person_id,
            date,
            increment
        )
    
    def get_person_count(self, person_id: int, days: int = 7) -> int:
        """Get aggregated count for a person over the last N days."""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days-1)
        
        return self.manager.get_aggregated_count(
            self.team_id,
            self.filter_hash,
            person_id,
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date, datetime.max.time())
        )
    
    def matches_threshold(self, person_id: int, threshold: int, days: int = 7) -> bool:
        """Check if person meets the behavioral threshold."""
        count = self.get_person_count(person_id, days)
        return count >= threshold
    
    def invalidate_cache(self) -> None:
        """Invalidate cached bytecode for this cohort."""
        if self._filter_hash:
            self.manager.invalidate_filter_cache(self.team_id, self._filter_hash)
            self._filter_hash = None