import json
import uuid
from typing import Any
from datetime import datetime

import structlog
from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_PERFORMANCE_EVENTS

logger = structlog.get_logger(__name__)


class NetworkPerformanceExtractor:
    """
    Extracts network performance data from PostHog session recordings.

    Processes RRWeb plugin events containing network performance data and converts
    them into structured events for ClickHouse storage, enabling HogQL querying.
    """
    NETWORK_PLUGIN_NAME = "posthog/network@1"
    RRWEB_NETWORK_PLUGIN_NAME = "rrweb/network@1"
    RRWEB_PLUGIN_EVENT_TYPE = 6  # RRWeb plugin event type

    def __init__(self, kafka_producer: KafkaProducer | None = None):
        self.kafka_producer = kafka_producer or KafkaProducer()

    def extract_performance_events_from_snapshots(
        self,
        snapshots: list[dict[str, Any]],
        session_id: str,
        team_id: int,
        distinct_id: str
    ) -> list[dict[str, Any]]:
        """Extract performance events from session recording snapshots."""
        performance_events = []

        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue

            if (snapshot.get("type") == self.RRWEB_PLUGIN_EVENT_TYPE and
                snapshot.get("data", {}).get("plugin") in [self.NETWORK_PLUGIN_NAME, self.RRWEB_NETWORK_PLUGIN_NAME]):

                events = self._extract_network_events_from_plugin(snapshot, session_id, team_id, distinct_id)
                performance_events.extend(events)

        return performance_events

    def _extract_network_events_from_plugin(
        self,
        plugin_event: dict[str, Any],
        session_id: str,
        team_id: int,
        distinct_id: str
    ) -> list[dict[str, Any]]:
        """Extract network events from a specific plugin event."""
        events = []
        plugin_data = plugin_event.get("data", {})
        payload = plugin_data.get("payload", {})

        if plugin_data.get("plugin") == self.RRWEB_NETWORK_PLUGIN_NAME:
            requests = payload.get("requests", [])
            if isinstance(requests, list):
                for request in requests:
                    event = self._create_performance_event_from_rrweb_request(
                        request, plugin_event, session_id, team_id, distinct_id
                    )
                    if event:
                        events.append(event)

        elif plugin_data.get("plugin") == self.NETWORK_PLUGIN_NAME:
            event = self._create_performance_event_from_posthog_request(
                payload, plugin_event, session_id, team_id, distinct_id
            )
            if event:
                events.append(event)

        return events

    def _create_performance_event_from_rrweb_request(
        self,
        request: dict[str, Any],
        plugin_event: dict[str, Any],
        session_id: str,
        team_id: int,
        distinct_id: str
    ) -> dict[str, Any] | None:
        """Create a performance event from RRWeb network request data."""
        try:
            window_id = self._extract_window_id(plugin_event)
            pageview_id = self._generate_pageview_id(request.get("name", ""), plugin_event.get("timestamp"))
            event = {
                "uuid": str(uuid.uuid4()),
                "session_id": session_id,
                "window_id": window_id,
                "pageview_id": pageview_id,
                "distinct_id": distinct_id,
                "timestamp": self._convert_timestamp(plugin_event.get("timestamp")),
                "time_origin": self._convert_timestamp(request.get("timeOrigin")),
                "entry_type": request.get("entryType", "resource"),
                "name": request.get("name", ""),
                "team_id": team_id,
                "current_url": request.get("name", ""),
                "start_time": self._safe_float(request.get("startTime")),
                "duration": self._safe_float(request.get("duration")),
                "redirect_start": self._safe_float(request.get("redirectStart")),
                "redirect_end": self._safe_float(request.get("redirectEnd")),
                "worker_start": self._safe_float(request.get("workerStart")),
                "fetch_start": self._safe_float(request.get("fetchStart")),
                "domain_lookup_start": self._safe_float(request.get("domainLookupStart")),
                "domain_lookup_end": self._safe_float(request.get("domainLookupEnd")),
                "connect_start": self._safe_float(request.get("connectStart")),
                "secure_connection_start": self._safe_float(request.get("secureConnectionStart")),
                "connect_end": self._safe_float(request.get("connectEnd")),
                "request_start": self._safe_float(request.get("requestStart")),
                "response_start": self._safe_float(request.get("responseStart")),
                "response_end": self._safe_float(request.get("responseEnd")),
                "decoded_body_size": self._safe_int(request.get("decodedBodySize")),
                "encoded_body_size": self._safe_int(request.get("encodedBodySize")),
                "transfer_size": self._safe_int(request.get("transferSize")),
                "initiator_type": request.get("initiatorType", ""),
                "next_hop_protocol": request.get("nextHopProtocol", ""),
                "render_blocking_status": request.get("renderBlockingStatus", ""),
                "response_status": self._safe_int(
                    request.get("responseStatus") if request.get("responseStatus") is not None 
                    else request.get("status")
                ),
                "dom_complete": self._safe_float(request.get("domComplete")),
                "dom_content_loaded_event": self._safe_float(request.get("domContentLoadedEvent")),
                "dom_interactive": self._safe_float(request.get("domInteractive")),
                "load_event_end": self._safe_float(request.get("loadEventEnd")),
                "load_event_start": self._safe_float(request.get("loadEventStart")),
                "redirect_count": self._safe_int(request.get("redirectCount")),
                "navigation_type": request.get("navigationType", ""),
                "unload_event_end": self._safe_float(request.get("unloadEventEnd")),
                "unload_event_start": self._safe_float(request.get("unloadEventStart")),
                "largest_contentful_paint_element": request.get("largestContentfulPaintElement", ""),
                "largest_contentful_paint_render_time": self._safe_float(request.get("largestContentfulPaintRenderTime")),
                "largest_contentful_paint_load_time": self._safe_float(request.get("largestContentfulPaintLoadTime")),
                "largest_contentful_paint_size": self._safe_float(request.get("largestContentfulPaintSize")),
                "largest_contentful_paint_id": request.get("largestContentfulPaintId", ""),
                "largest_contentful_paint_url": request.get("largestContentfulPaintUrl", ""),
            }

            return event

        except Exception as e:
            logger.warning("Failed to create performance event from RRWeb request", error=str(e))
            return None

    def _create_performance_event_from_posthog_request(
        self,
        payload: dict[str, Any],
        plugin_event: dict[str, Any],
        session_id: str,
        team_id: int,
        distinct_id: str
    ) -> dict[str, Any] | None:
        """Create a performance event from PostHog network request data."""
        try:
            window_id = self._extract_window_id(plugin_event)
            pageview_id = self._generate_pageview_id(payload.get("name", ""), plugin_event.get("timestamp"))
            event = {
                "uuid": str(uuid.uuid4()),
                "session_id": session_id,
                "window_id": window_id,
                "pageview_id": pageview_id,
                "distinct_id": distinct_id,
                "timestamp": self._convert_timestamp(plugin_event.get("timestamp")),
                "time_origin": self._convert_timestamp(payload.get("time_origin")),
                "entry_type": payload.get("entry_type", "resource"),
                "name": payload.get("name", ""),
                "team_id": team_id,
                "current_url": payload.get("name", ""),
                "start_time": self._safe_float(payload.get("start_time")),
                "duration": self._safe_float(payload.get("duration")),
                "redirect_start": self._safe_float(payload.get("redirect_start")),
                "redirect_end": self._safe_float(payload.get("redirect_end")),
                "worker_start": self._safe_float(payload.get("worker_start")),
                "fetch_start": self._safe_float(payload.get("fetch_start")),
                "domain_lookup_start": self._safe_float(payload.get("domain_lookup_start")),
                "domain_lookup_end": self._safe_float(payload.get("domain_lookup_end")),
                "connect_start": self._safe_float(payload.get("connect_start")),
                "secure_connection_start": self._safe_float(payload.get("secure_connection_start")),
                "connect_end": self._safe_float(payload.get("connect_end")),
                "request_start": self._safe_float(payload.get("request_start")),
                "response_start": self._safe_float(payload.get("response_start")),
                "response_end": self._safe_float(payload.get("response_end")),
                "decoded_body_size": self._safe_int(payload.get("decoded_body_size")),
                "encoded_body_size": self._safe_int(payload.get("encoded_body_size")),
                "transfer_size": self._safe_int(payload.get("transfer_size")),
                "initiator_type": payload.get("initiator_type", ""),
                "next_hop_protocol": payload.get("next_hop_protocol", ""),
                "render_blocking_status": payload.get("render_blocking_status", ""),
                "response_status": self._safe_int(payload.get("response_status")),
                "dom_complete": self._safe_float(payload.get("dom_complete")),
                "dom_content_loaded_event": self._safe_float(payload.get("dom_content_loaded_event")),
                "dom_interactive": self._safe_float(payload.get("dom_interactive")),
                "load_event_end": self._safe_float(payload.get("load_event_end")),
                "load_event_start": self._safe_float(payload.get("load_event_start")),
                "redirect_count": self._safe_int(payload.get("redirect_count")),
                "navigation_type": payload.get("navigation_type", ""),
                "unload_event_end": self._safe_float(payload.get("unload_event_end")),
                "unload_event_start": self._safe_float(payload.get("unload_event_start")),
                "largest_contentful_paint_element": payload.get("largest_contentful_paint_element", ""),
                "largest_contentful_paint_render_time": self._safe_float(payload.get("largest_contentful_paint_render_time")),
                "largest_contentful_paint_load_time": self._safe_float(payload.get("largest_contentful_paint_load_time")),
                "largest_contentful_paint_size": self._safe_float(payload.get("largest_contentful_paint_size")),
                "largest_contentful_paint_id": payload.get("largest_contentful_paint_id", ""),
                "largest_contentful_paint_url": payload.get("largest_contentful_paint_url", ""),
            }

            return event

        except Exception as e:
            logger.warning("Failed to create performance event from PostHog request", error=str(e))
            return None

    def send_performance_events_to_kafka(self, events: list[dict[str, Any]]) -> None:
        """Send performance events to Kafka for ClickHouse ingestion."""
        for event in events:
            try:
                self.kafka_producer.produce(
                    topic=KAFKA_PERFORMANCE_EVENTS,
                    data=json.dumps(event),
                    key=event["session_id"]
                )
            except Exception:
                logger.exception("Failed to send performance event to Kafka")

    def process_session_recording(
        self,
        snapshots: list[dict[str, Any]],
        session_id: str,
        team_id: int,
        distinct_id: str
    ) -> int:
        """Process a complete session recording and extract all performance events."""
        try:
            performance_events = self.extract_performance_events_from_snapshots(
                snapshots, session_id, team_id, distinct_id
            )

            if performance_events:
                self.send_performance_events_to_kafka(performance_events)
                logger.info(
                    "Extracted and sent performance events",
                    session_id=session_id,
                    event_count=len(performance_events)
                )

            return len(performance_events)

        except Exception:
            logger.exception("Failed to process session recording", session_id=session_id)
            return 0

    # Utility methods

    def _extract_window_id(self, plugin_event: dict[str, Any]) -> str:
        """Extract window ID from plugin event."""
        data = plugin_event.get("data", {})
        if "window_id" in data:
            return str(data["window_id"])

        # Fallback to session_id if window_id not available
        if "session_id" in data:
            return str(data["session_id"])

        return "unknown"

    def _generate_pageview_id(self, url: str, timestamp: Any) -> str:
        """Generate a consistent pageview ID based on URL and timestamp."""
        base_url = url.split("?")[0] if url else "unknown"
        timestamp_str = str(timestamp) if timestamp else "0"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{base_url}#{timestamp_str}"))

    def _convert_timestamp(self, timestamp: Any) -> datetime | None:
        """Convert various timestamp formats to datetime."""
        if not timestamp:
            return None

        try:
            if isinstance(timestamp, int | float):
                # Handle both milliseconds and seconds
                if timestamp > 1e12:  # Likely milliseconds
                    return datetime.fromtimestamp(timestamp / 1000.0)
                else:  # Likely seconds
                    return datetime.fromtimestamp(timestamp)
            elif isinstance(timestamp, str):
                return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                return None
        except (ValueError, TypeError):
            return None

    def _safe_float(self, value: Any) -> float:
        """Safely convert value to float."""
        try:
            return float(value) if value is not None else 0.0
        except (ValueError, TypeError):
            return 0.0

    def _safe_int(self, value: Any) -> int:
        """Safely convert value to int."""
        try:
            return int(value) if value is not None else 0
        except (ValueError, TypeError):
            return 0


def extract_performance_events_from_session_recording(
    snapshots: list[dict[str, Any]],
    session_id: str,
    team_id: int,
    distinct_id: str
) -> int:
    """
    Convenience function to extract performance events from a session recording.

    Returns the number of performance events extracted and sent to Kafka.
    """
    extractor = NetworkPerformanceExtractor()
    return extractor.process_session_recording(snapshots, session_id, team_id, distinct_id)
