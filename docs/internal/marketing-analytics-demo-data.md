# Marketing analytics demo traffic

`generate_marketing_demo_data` generates returning visitors and a mix of single-page and multi-page sessions for paid and free channels. Repeated pageviews share a session ID and have later timestamps, so visitors, sessions, pageviews and engagement metrics can be reviewed separately.

Use a fresh local project and at least twice the dashboard date range for previous-period comparisons. The command defaults to 60 days, covering two 30-day periods. It also configures demo warehouse sources and goals; it is not a traffic-only seeder.

```sh
DEBUG=1 python manage.py generate_marketing_demo_data --team-id <demo-project-id> --days-past 60 --scale 0.1
```

Existing seeded events are unchanged. Generate into a new project to avoid mixing old and new traffic distributions.
