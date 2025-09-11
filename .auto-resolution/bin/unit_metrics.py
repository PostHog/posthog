import json
import time
import logging
import http.client

from prometheus_client import CollectorRegistry, Gauge, generate_latest, multiprocess

logger = logging.getLogger(__name__)

UNIT_CONNECTIONS_ACCEPTED_TOTAL = Gauge(
    "unit_connections_accepted_total",
    "",
    multiprocess_mode="livesum",
)
UNIT_CONNECTIONS_ACTIVE = Gauge(
    "unit_connections_active",
    "",
    multiprocess_mode="livesum",
)
UNIT_CONNECTIONS_CLOSED = Gauge(
    "unit_connections_closed",
    "",
    multiprocess_mode="livesum",
)
UNIT_CONNECTIONS_IDLE = Gauge(
    "unit_connections_idle",
    "",
    multiprocess_mode="livesum",
)
UNIT_CONNECTIONS_TOTAL = Gauge(
    "unit_requests_total",
    "",
    multiprocess_mode="livesum",
)
UNIT_PROCESSES_RUNNING_GAUGE = Gauge(
    "unit_application_processes_running", "", multiprocess_mode="livesum", labelnames=["application"]
)
UNIT_PROCESSES_STARTING_GAUGE = Gauge(
    "unit_application_processes_starting", "", multiprocess_mode="livesum", labelnames=["application"]
)
UNIT_PROCESSES_IDLE_GAUGE = Gauge(
    "unit_application_processes_idle", "", multiprocess_mode="livesum", labelnames=["application"]
)
UNIT_REQUESTS_ACTIVE_GAUGE = Gauge(
    "unit_application_requests_active", "", multiprocess_mode="livesum", labelnames=["application"]
)


def application(environ, start_response):
    retries = 5
    try:
        connection = http.client.HTTPConnection("localhost:8181")
        connection.request("GET", "/status")
        response = connection.getresponse()

        statj = json.loads(response.read())
    except Exception:
        if retries > 0:
            retries -= 1
            time.sleep(1)
            return application(environ, start_response)
        else:
            raise
    finally:
        try:
            connection.close()
        except Exception as e:
            logger.exception("Failed to close connection to unit: ", e)

    UNIT_CONNECTIONS_ACCEPTED_TOTAL.set(statj["connections"]["accepted"])
    UNIT_CONNECTIONS_ACTIVE.set(statj["connections"]["active"])
    UNIT_CONNECTIONS_IDLE.set(statj["connections"]["idle"])
    UNIT_CONNECTIONS_CLOSED.set(statj["connections"]["closed"])
    UNIT_CONNECTIONS_TOTAL.set(statj["requests"]["total"])

    for app in statj["applications"].keys():
        UNIT_PROCESSES_RUNNING_GAUGE.labels(application=app).set(statj["applications"][app]["processes"]["running"])
        UNIT_PROCESSES_STARTING_GAUGE.labels(application=app).set(statj["applications"][app]["processes"]["starting"])
        UNIT_PROCESSES_IDLE_GAUGE.labels(application=app).set(statj["applications"][app]["processes"]["idle"])
        UNIT_REQUESTS_ACTIVE_GAUGE.labels(application=app).set(statj["applications"][app]["requests"]["active"])

    start_response("200 OK", [("Content-Type", "text/plain")])
    # Create the prometheus multi-process metric registry here
    # This will aggregate metrics we send from the Django app
    # We prepend our unit metrics here.
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    yield generate_latest(registry)
