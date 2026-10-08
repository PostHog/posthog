# Test cases for beat-schedule-must-not-be-random.
# ruff: noqa

# ruleid: beat-schedule-must-not-be-random
sender.add_periodic_task(crontab(hour="0", minute=str(randrange(0, 40))), send_usage_report.s())

# ruleid: beat-schedule-must-not-be-random
sender.add_periodic_task(crontab(minute=str(random.randint(0, 59))), refresh_cache.s())

# ruleid: beat-schedule-must-not-be-random
schedule = crontab(hour=str(random.choice(["1", "2"])), minute="0")

# ok: beat-schedule-must-not-be-random
sender.add_periodic_task(crontab(hour="2", minute="23"), sweep_retention.s())

# ok: beat-schedule-must-not-be-random
sender.add_periodic_task(crontab(hour="0", minute=instance_spread_minute("send license usage", 40)), send_license.s())

# ok: beat-schedule-must-not-be-random
jitter = randrange(0, 40)
