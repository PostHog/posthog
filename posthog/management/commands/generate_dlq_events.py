import json
import uuid
import random
from datetime import datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand

from posthog.clickhouse.client import sync_execute
from posthog.models.team.team import Team


class Command(BaseCommand):
    help = "Generate dead letter queue events for development/testing"

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=100, help="Number of events to generate (default: 100)")
        parser.add_argument("--team-id", type=int, help="Team ID to generate events for")
        parser.add_argument("--days-back", type=int, default=7, help="Generate events from N days back (default: 7)")

    def handle(self, *args, **options):
        count = options["count"]
        team_id = options["team_id"]
        days_back = options["days_back"]

        # Get team
        if team_id:
            try:
                team = Team.objects.get(pk=team_id)
            except Team.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Team with ID {team_id} does not exist!"))
                return
        else:
            team = Team.objects.first()
            if not team:
                self.stdout.write(self.style.ERROR("No teams found! Please create a team first."))
                return

        self.stdout.write(f"Generating {count} dead letter queue events for team: {team.name}")

        # Generate events
        events_created = 0
        for _ in range(count):
            event_data = self._generate_dlq_event(team, days_back)

            # Insert into ClickHouse
            self._insert_event_to_clickhouse(event_data)
            events_created += 1

            if events_created % 10 == 0:
                self.stdout.write(f"Created {events_created} events...")

        self.stdout.write(self.style.SUCCESS(f"Successfully created {events_created} dead letter queue events"))

    def _generate_dlq_event(self, team: Team, days_back: int) -> dict[str, Any]:
        """Generate a realistic dead letter queue event"""
        # Generate random timestamp within the specified range
        now = datetime.now()
        random_days_ago = random.randint(0, days_back)
        random_hours_ago = random.randint(0, 23)
        random_minutes_ago = random.randint(0, 59)

        event_time = now - timedelta(days=random_days_ago, hours=random_hours_ago, minutes=random_minutes_ago)

        # Generate event UUID
        event_uuid = str(uuid.uuid4())

        # Generate distinct ID
        distinct_id = str(uuid.uuid4())

        # Generate realistic properties
        properties = self._generate_event_properties()

        # Generate raw payload
        raw_payload = self._generate_raw_payload(event_uuid, distinct_id, properties)

        # Generate error details
        error_details = self._generate_error_details()

        # Generate elements chain (sometimes empty, sometimes with data)
        elements_chain = ""

        # Generate IP address
        ip = self._generate_ip_address()

        # Generate site URL
        site_url = self._generate_site_url()

        # Generate tags
        tags = self._generate_tags()

        return {
            "id": str(uuid.uuid4()),
            "event_uuid": event_uuid,
            "event": random.choice(["$autocapture", "$pageview", "$identify", "$set", "$set_once", "custom_event"]),
            "properties": json.dumps(properties),
            "distinct_id": distinct_id,
            "team_id": str(team.pk),
            "elements_chain": elements_chain,
            "created_at": "1970-01-01 00:00:00",  # Default value from sample
            "ip": ip,
            "site_url": site_url,
            "now": event_time.strftime("%Y-%m-%d %H:%M:%S"),
            "raw_payload": json.dumps(raw_payload),
            "error_timestamp": event_time.strftime("%Y-%m-%d %H:%M:%S"),
            "error_location": error_details["location"],
            "error": error_details["message"],
            "tags": tags,
            "_timestamp": event_time.strftime("%Y-%m-%d %H:%M:%S"),
            "_offset": str(random.randint(100, 10000)),
        }

    def _generate_event_properties(self) -> dict[str, Any]:
        """Generate realistic event properties"""
        browsers = ["Chrome", "Firefox", "Safari", "Edge"]
        os_versions = ["Windows 10", "Windows 11", "macOS 14", "iOS 17", "Android 14"]
        countries = ["US", "UK", "CA", "AU", "DE", "FR", "JP", "IN", "BR", "MX"]
        cities = ["New York", "London", "San Francisco", "Berlin", "Tokyo", "Sydney", "Toronto", "Paris"]

        properties = {
            "$lib": "web",
            "$lib_version": f"1.{random.randint(250, 300)}.0",
            "$browser": random.choice(browsers),
            "$browser_version": random.randint(100, 150),
            "$os": random.choice(os_versions),
            "$device_type": random.choice(["Desktop", "Mobile", "Tablet"]),
            "$screen_width": random.choice([1920, 1366, 1440, 1536, 414, 375]),
            "$screen_height": random.choice([1080, 768, 900, 864, 896, 812]),
            "$viewport_width": random.choice([1920, 1366, 1440, 1536, 414, 375]),
            "$viewport_height": random.choice([1080, 768, 900, 864, 896, 812]),
            "$timezone": random.choice(["America/New_York", "Europe/London", "Asia/Tokyo", "Australia/Sydney"]),
            "$timezone_offset": random.choice([-300, -240, -180, 0, 60, 120, 480, 540]),
            "$referrer": random.choice(
                ["https://www.google.com/", "https://twitter.com/", "https://linkedin.com/", ""]
            ),
            "$referring_domain": random.choice(["google.com", "twitter.com", "linkedin.com", ""]),
            "$current_url": f"https://example.com/page/{random.randint(1, 100)}",
            "$pathname": f"/page/{random.randint(1, 100)}",
            "$session_id": str(uuid.uuid4()),
            "$device_id": str(uuid.uuid4()),
            "$user_id": str(random.randint(1000000000000, 9999999999999)) if random.random() < 0.3 else None,
            "$is_identified": random.choice([True, False]),
            "$raw_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "$insert_id": f"{random.choice(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j'])}{random.randint(100000000000000, 999999999999999)}",
            "$time": random.uniform(1700000000, 1800000000),
            "$sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "$geoip_country_name": random.choice(
                ["United States", "United Kingdom", "Canada", "Australia", "Germany", "France"]
            ),
            "$geoip_country_code": random.choice(countries),
            "$geoip_city_name": random.choice(cities),
            "$geoip_latitude": random.uniform(-90, 90),
            "$geoip_longitude": random.uniform(-180, 180),
            "$session_recording_network_payload_capture": {
                "capturePerformance": {"network_timing": True, "web_vitals": True}
            },
            "$web_vitals_enabled_server_side": True,
            "$recording_status": random.choice(["enabled", "disabled"]),
            "$autocapture_disabled_server_side": False,
            "$exception_capture_enabled_server_side": False,
            "$dead_clicks_enabled_server_side": False,
            "$feature_flags": {},
            "$active_feature_flags": [],
            "$feature_flag_payloads": {},
            "$feature_flag_request_id": str(uuid.uuid4()),
            "$ce_version": 1,
            "$process_person_profile": True,
            "$configured_session_timeout_ms": 1800000,
            "$replay_sample_rate": None,
            "$replay_minimum_duration": None,
            "$session_recording_canvas_recording": {},
            "$sdk_debug_session_start": random.randint(1700000000000, 1800000000000),
            "$sdk_debug_retry_queue_size": 0,
            "$sdk_debug_replay_internal_buffer_length": 0,
            "$sdk_debug_replay_internal_buffer_size": 0,
            "$sdk_debug_current_session_duration": None,
            "$lib_rate_limit_remaining_tokens": random.randint(50, 100),
            "$window_id": str(uuid.uuid4()),
            "$pageview_id": str(uuid.uuid4()),
            "$browser_language": "en-US",
            "$browser_language_prefix": "en",
            "$host": "example.com",
            "$session_entry_url": f"https://example.com/entry/{random.randint(1, 100)}",
            "$session_entry_pathname": f"/entry/{random.randint(1, 100)}",
            "$session_entry_host": "example.com",
            "$session_entry_referrer": random.choice(
                ["https://www.google.com/", "https://twitter.com/", "https://linkedin.com/", ""]
            ),
            "$session_entry_referring_domain": random.choice(["google.com", "twitter.com", "linkedin.com", ""]),
            "$session_entry_search_engine": random.choice(["google", "bing", "duckduckgo", None]),
            "$search_engine": random.choice(["google", "bing", "duckduckgo", None]),
            "$initialization_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "$config_defaults": "unset",
            "$web_vitals_allowed_metrics": None,
            "$event_type": random.choice(["click", "pageview", "form_submit", "scroll"]),
            "$el_text": random.choice(["Sign Up", "Learn More", "Get Started", "Contact Us", "Download", "Subscribe"]),
            "$external_click_url": random.choice(
                [None, "https://youtube.com/watch?v=example", "https://github.com/example"]
            ),
            "$device": random.choice(["iPhone", "Android", "Desktop", "iPad"]),
            "token": f"phc_{''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789', k=40))}",
        }

        # Add some geoip properties
        if random.random() < 0.7:
            properties.update(
                {
                    "$geoip_continent_name": random.choice(
                        ["North America", "Europe", "Asia", "Oceania", "South America", "Africa"]
                    ),
                    "$geoip_continent_code": random.choice(["NA", "EU", "AS", "OC", "SA", "AF"]),
                    "$geoip_postal_code": str(random.randint(10000, 99999)),
                    "$geoip_accuracy_radius": random.randint(10, 1000),
                    "$geoip_time_zone": random.choice(
                        ["America/New_York", "Europe/London", "Asia/Tokyo", "Australia/Sydney"]
                    ),
                    "$geoip_subdivision_1_name": random.choice(
                        ["New York", "California", "Texas", "Florida", "Ontario", "Quebec"]
                    ),
                    "$geoip_subdivision_1_code": random.choice(["NY", "CA", "TX", "FL", "ON", "QC"]),
                }
            )

        # Add $set and $set_once properties
        if random.random() < 0.5:
            properties["$set"] = {
                "$geoip_city_name": properties.get("$geoip_city_name"),
                "$geoip_country_name": properties.get("$geoip_country_name"),
                "$geoip_country_code": properties.get("$geoip_country_code"),
                "$os": properties.get("$os"),
                "$browser": properties.get("$browser"),
                "$device_type": properties.get("$device_type"),
            }

            properties["$set_once"] = {
                "$initial_geoip_city_name": properties.get("$geoip_city_name"),
                "$initial_geoip_country_name": properties.get("$geoip_country_name"),
                "$initial_geoip_country_code": properties.get("$geoip_country_code"),
                "$initial_os": properties.get("$os"),
                "$initial_browser": properties.get("$browser"),
                "$initial_device_type": properties.get("$device_type"),
            }

        return properties

    def _generate_raw_payload(self, event_uuid: str, distinct_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        """Generate raw payload for the event"""
        return {
            "uuid": event_uuid,
            "event": random.choice(["$autocapture", "$pageview", "$identify", "$set", "$set_once", "custom_event"]),
            "properties": properties,
            "offset": random.randint(100, 10000),
            "distinct_id": distinct_id,
            "ip": None,
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "token": properties.get("token"),
        }

    def _generate_error_details(self) -> dict[str, str]:
        """Generate realistic error details"""
        error_types = [
            {
                "message": 'Event ingestion failed. Error: insert or update on table "posthog_person" violates foreign key constraint "posthog_person_team_id_325c1b73_fk_posthog_team_id"',
                "location": "plugin_server_ingest_event:processPersonsStep",
            },
            {
                "message": 'Event ingestion failed. Error: duplicate key value violates unique constraint "posthog_person_distinct_id_team_id_key"',
                "location": "plugin_server_ingest_event:processPersonsStep",
            },
            {
                "message": 'Event ingestion failed. Error: invalid input syntax for type uuid: "invalid-uuid"',
                "location": "plugin_server_ingest_event:validateEvent",
            },
            {
                "message": 'Event ingestion failed. Error: column "non_existent_column" does not exist',
                "location": "plugin_server_ingest_event:processEvent",
            },
            {
                "message": "Event ingestion failed. Error: timeout expired",
                "location": "plugin_server_ingest_event:processEvent",
            },
            {
                "message": "Event ingestion failed. Error: connection to database failed",
                "location": "plugin_server_ingest_event:processEvent",
            },
            {
                "message": "Event ingestion failed. Error: JSON parsing failed",
                "location": "plugin_server_ingest_event:parseEvent",
            },
        ]

        return random.choice(error_types)

    def _generate_ip_address(self) -> str:
        """Generate a realistic IP address"""
        if random.random() < 0.8:
            # Generate IPv4
            return (
                f"{random.randint(1, 223)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
            )
        else:
            # Sometimes empty
            return ""

    def _generate_site_url(self) -> str:
        """Generate a realistic site URL"""
        sites = [
            "https://example.com",
            "https://myapp.com",
            "https://test-site.com",
            "https://demo-app.com",
            "https://localhost:3000",
            "",
        ]
        return random.choice(sites)

    def _generate_tags(self) -> list:
        """Generate tags for the event"""
        tag_combinations = [
            ["plugin_server", "ingest_event"],
            ["plugin_server", "process_event"],
            ["plugin_server", "validate_event"],
            ["plugin_server", "parse_event"],
            ["ingest_event", "error"],
            ["process_event", "error"],
        ]
        return random.choice(tag_combinations)

    def _insert_event_to_clickhouse(self, event_data: dict[str, Any]):
        """Insert event data into ClickHouse"""
        query = """
        INSERT INTO events_dead_letter_queue (
            id, event_uuid, event, properties, distinct_id, team_id, elements_chain,
            created_at, ip, site_url, now, raw_payload, error_timestamp,
            error_location, error, tags, _timestamp, _offset
        ) VALUES (
            %(id)s, %(event_uuid)s, %(event)s, %(properties)s, %(distinct_id)s, %(team_id)s, %(elements_chain)s,
            %(created_at)s, %(ip)s, %(site_url)s, %(now)s, %(raw_payload)s, %(error_timestamp)s,
            %(error_location)s, %(error)s, %(tags)s, %(_timestamp)s, %(_offset)s
        )
        """

        sync_execute(query, event_data)
