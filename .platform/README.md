# PostHog for Platform.sh

[![Deploy with Platform.sh](https://platform.sh/images/deploy/deploy-button-lg-blue.svg)](https://console.platform.sh/projects/create-project/?template=https://github.com/posthog/posthog&utm_campaign=deploy_on_platform?utm_medium=button&utm_source=affiliate_links&utm_content=https://github.com/posthog/posthog)

This template builds PostHog on Platform.sh, using the gunicorn application server. In the deployment process you will be able to choose from multiple regions (from Australia to the US West Coast) with strict data locality guarantees which could help you with latency as well as GDPR, German BDSG, Canadian PIPEDA, and the Australian Privacy Act compliance.

## Services

* Python 3.8
* PostgreSQL 12.X
* Persistent Redis 5.x

## Customizations

The following files have been added to a basic PostHog configuration. 

* The `.platform/applications.yaml`, `.platform/services.yaml`, and `.platform/routes.yaml` and `.environment` files have been added.  These provide Platform.sh-specific configuration and are present in all projects on Platform.sh.  You may customize them as you see fit.

Some specific configuration options you may want to notice:

* In `.platform/applications.yaml` the `workers.worker.commands.start` the option `--concurrency=2` controls the concurrency of the celery workers on a production system, depending on the amount of resources you allocate you will want to bump it higher
* In `.environment` the `SECRET_KEY` variable gets its value from a per-project stable generated secret. In a real production system you may want to have the value different between staging environments and the production environment
* In `.platform/applications.yaml` the `variables.env.NODE_OPTIONS` with `max_old_space_size` has a magical value of 1536 this is because the build containers has 2GB of memory and would avoid getting webpack oom killed.
* In `.platform/service.yaml` we allocate 2GB to the database and 0.5GB to the Redis instance, a real production system will probably require more, you have 5GB available to allocate in the base plan (and you can of course add more)

## References

* [Python on Platform.sh](https://docs.platform.sh/languages/python.html)
