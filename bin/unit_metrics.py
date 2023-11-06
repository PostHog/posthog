import os
import http.client
import json

from prometheus_client import CollectorRegistry, Gauge, multiprocess, generate_latest

def application(environ, start_response):
    connection = http.client.HTTPConnection("localhost:8081")
    connection.request("GET", "/status")
    response = connection.getresponse()

    statj = json.loads(response.read())
    connection.close()

    metrics = []
    metrics.append("unit_connections_accepted_total {}".format(statj["connections"]["accepted"]))
    metrics.append("unit_connections_active {}".format(statj["connections"]["active"]))
    metrics.append("unit_connections_idle {}".format(statj["connections"]["idle"]))
    metrics.append("unit_connections_closed_total {}".format(statj["connections"]["closed"]))
    metrics.append("unit_requests_total {}".format(statj["requests"]["total"]))

    for application in statj["applications"].keys():
        metrics.append("unit_application_" + application + "_processes_running {}".format(statj["applications"][application]["processes"]["running"]))
        metrics.append("unit_application_" + application + "_processes_starting {}".format(statj["applications"][application]["processes"]["starting"]))
        metrics.append("unit_application_" + application + "_processes_idle {}".format(statj["applications"][application]["processes"]["idle"]))
        metrics.append("unit_application_" + application + "_requests_active {}".format(statj["applications"][application]["requests"]["active"]))

    start_response('200 OK', [("Content-Type", "text/plain")])
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    yield str.encode("\n".join(metrics) + "\n" + generate_latest(registry).decode('utf-8'))
