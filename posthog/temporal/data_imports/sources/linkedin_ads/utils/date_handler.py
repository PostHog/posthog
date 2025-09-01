"""LinkedIn Ads date range calculation and validation logic."""

import datetime as dt
from typing import Optional

import structlog

from ..utils.constants import MAX_DATE_RANGE_DAYS
from ..utils.types import DateRange, IncrementalValue
from ..utils.utils import validate_date_format

logger = structlog.get_logger(__name__)


class LinkedinAdsDateHandler:
    """Handles date range calculations and validation for LinkedIn Ads API."""

    def __init__(self, max_date_range_days: int = MAX_DATE_RANGE_DAYS):
        """Initialize date handler.

        Args:
            max_date_range_days: Maximum allowed date range in days
        """
        self.max_date_range_days = max_date_range_days

    def calculate_date_range(self, date_start: Optional[str] = None, date_end: Optional[str] = None) -> DateRange:
        """Calculate and validate date range for analytics requests.

        Args:
            date_start: Start date in YYYY-MM-DD format (optional)
            date_end: End date in YYYY-MM-DD format (optional)

        Returns:
            Tuple of (start_date, end_date) as datetime objects

        Raises:
            ValueError: If date formats are invalid
        """
        # Validate date formats if provided
        if date_start and not validate_date_format(date_start):
            raise ValueError(f"Invalid date_start format: '{date_start}'. Expected YYYY-MM-DD format.")

        if date_end and not validate_date_format(date_end):
            raise ValueError(f"Invalid date_end format: '{date_end}'. Expected YYYY-MM-DD format.")

        # Calculate date range based on provided parameters
        if date_start or date_end:
            start_date, end_date = self._parse_provided_dates(date_start, date_end)
        else:
            start_date, end_date = self._get_default_date_range()

        # Finally, validate and adjust date range if necessary
        start_date, end_date = self._validate_and_adjust_date_range(start_date, end_date)

        return start_date, end_date

    def calculate_incremental_date_range(
        self, last_value: IncrementalValue, sync_frequency_interval: Optional[dt.timedelta] = None
    ) -> str:
        """Calculate start date for incremental sync.

        Args:
            last_value: Last incremental value (date string or datetime object)
            sync_frequency_interval: Sync frequency to limit lookback period

        Returns:
            Start date string in YYYY-MM-DD format
        """
        if sync_frequency_interval:
            return self._calculate_with_sync_frequency(last_value, sync_frequency_interval)
        else:
            return self._calculate_without_sync_frequency(last_value)

    def format_linkedin_date_range(self, start_date: dt.datetime, end_date: dt.datetime) -> str:
        """Format date range for LinkedIn API parameters.

        Args:
            start_date: Start date as datetime object
            end_date: End date as datetime object

        Returns:
            LinkedIn API formatted date range string
        """
        return (
            f"(start:(year:{start_date.year},month:{start_date.month},day:{start_date.day}),"
            f"end:(year:{end_date.year},month:{end_date.month},day:{end_date.day}))"
        )

    def _parse_provided_dates(self, date_start: Optional[str], date_end: Optional[str]) -> DateRange:
        """Parse provided date strings into datetime objects.

        Args:
            date_start: Start date string (optional)
            date_end: End date string (optional)

        Returns:
            Tuple of (start_date, end_date) as datetime objects
        """
        if date_start and not date_end:
            # Incremental case: start date provided, use current date as end
            try:
                start_date = dt.datetime.strptime(date_start, "%Y-%m-%d")
                end_date = dt.datetime.now() - dt.timedelta(days=1)  # Yesterday
                logger.info(
                    "Using incremental date range",
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                )
            except ValueError as e:
                logger.warning("Invalid start date format, using default range", date_start=date_start, error=str(e))
                return self._get_default_date_range()

        elif date_end and not date_start:
            # End date provided, use 30 days before as start
            try:
                end_date = dt.datetime.strptime(date_end, "%Y-%m-%d")
                start_date = end_date - dt.timedelta(days=30)
            except ValueError as e:
                logger.warning("Invalid end date format, using default range", date_end=date_end, error=str(e))
                return self._get_default_date_range()

        else:
            # Both dates provided
            try:
                if date_start is None or date_end is None:
                    raise ValueError("Both dates must be provided")
                start_date = dt.datetime.strptime(date_start, "%Y-%m-%d")
                end_date = dt.datetime.strptime(date_end, "%Y-%m-%d")

                if start_date >= end_date:
                    logger.warning(
                        "Start date >= end date, adjusting to valid range", start_date=start_date, end_date=end_date
                    )
                    start_date = end_date - dt.timedelta(days=30)

            except ValueError as e:
                logger.warning(
                    "Invalid date format, using default range", date_start=date_start, date_end=date_end, error=str(e)
                )
                return self._get_default_date_range()

        return start_date, end_date

    def _get_default_date_range(self) -> DateRange:
        """Get default date range (last 30 days).

        Returns:
            Tuple of (start_date, end_date) as datetime objects
        """
        end_date = dt.datetime.now() - dt.timedelta(days=1)  # Yesterday
        start_date = end_date - dt.timedelta(days=30)
        return start_date, end_date

    def _validate_and_adjust_date_range(self, start_date: dt.datetime, end_date: dt.datetime) -> DateRange:
        """Validate and adjust date range to respect API limits.

        Args:
            start_date: Start date as datetime object
            end_date: End date as datetime object

        Returns:
            Tuple of (adjusted_start_date, adjusted_end_date)
        """
        date_range_days = (end_date - start_date).days

        if date_range_days > self.max_date_range_days:
            logger.warning(
                "Date range too large, limiting to maximum allowed",
                original_start=start_date,
                original_end=end_date,
                max_days=self.max_date_range_days,
            )
            start_date = end_date - dt.timedelta(days=self.max_date_range_days)

        return start_date, end_date

    def _calculate_with_sync_frequency(
        self, last_value: IncrementalValue, sync_frequency_interval: dt.timedelta
    ) -> str:
        """Calculate start date with sync frequency limit.

        Args:
            last_value: Last incremental value
            sync_frequency_interval: Sync frequency interval

        Returns:
            Start date string in YYYY-MM-DD format
        """
        # Calculate start date based on sync frequency interval
        now = dt.datetime.now()
        max_lookback_days = max(1, sync_frequency_interval.days)
        calculated_start = now - dt.timedelta(days=max_lookback_days)

        # Parse last_value into datetime
        if hasattr(last_value, "strftime") and last_value is not None:
            if isinstance(last_value, dt.datetime):
                last_value_date = last_value
            elif isinstance(last_value, dt.date):
                last_value_date = dt.datetime.combine(last_value, dt.time.min)
            else:
                # Fallback for other types with strftime (shouldn't happen)
                last_value_date = dt.datetime.strptime(str(last_value), "%Y-%m-%d")
        else:
            last_value_date = dt.datetime.strptime(str(last_value), "%Y-%m-%d")

        # Use the later of: last_value or calculated_start
        effective_start = max(last_value_date, calculated_start)
        date_start = effective_start.strftime("%Y-%m-%d")

        logger.info(
            "Using incremental date with sync frequency limit",
            last_value=last_value,
            sync_frequency_interval=sync_frequency_interval,
            max_lookback_days=max_lookback_days,
            calculated_start=calculated_start.strftime("%Y-%m-%d"),
            effective_start=effective_start.strftime("%Y-%m-%d"),
            date_start=date_start,
        )

        return date_start

    def _calculate_without_sync_frequency(self, last_value: IncrementalValue) -> str:
        """Calculate start date without sync frequency limit.

        Args:
            last_value: Last incremental value

        Returns:
            Start date string in YYYY-MM-DD format
        """
        if hasattr(last_value, "strftime") and last_value is not None:
            date_start = last_value.strftime("%Y-%m-%d")
        else:
            date_start = str(last_value)

        logger.info("Using incremental date without sync frequency limit", date_start=date_start)

        return date_start
