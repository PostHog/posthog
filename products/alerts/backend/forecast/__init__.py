"""The forecast detector: it forecasts the next point from the points before it, then compares the actual
value with the forecast.

Like the AI judge, it is not a registry detector, because its gateway call needs a team to attribute the
call to and a person to check the rollout for. ``rules`` holds the comparison as pure functions,
``access`` the rollout and cadence rules, and ``scorer`` the gateway call.
"""
