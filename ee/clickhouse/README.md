## Clickhouse Support (Enterprise Feature)

To accomodate high volume deployments, PostHog can use Clickhouse instead of Postgres. Clickhouse isn't used by default because Postgres is easier to deploy and maintain on smaller instances and on platforms such as Heroku.

Clickhouse Support works by swapping in separate queries and classes in the system for models that are most impacted by high volume usage (ex: events and actions).

### Migrations and Models

The `django_clickhouse` orm is used to manage migrations and models. The ORM is used to mimic the django model and migration structure in the main folder.

### Queries

Queries parallel the queries folder in the main folder however, clickhouse queries are written in SQL and do not utilize the ORM.

### Tests

The tests are inherited from the main folder. The Clickhouse query classes are based off `BaseQuery` so their run function should work just as the Django ORM backed query classes. These classes are called with the paramterized tests declared in the main folder which allows the same suite of tests to be run with different implementations.

### Views

Views contain Viewset classes that are not backed by models. Instead the views query Clickhouse tables using SQL. These views match the interface provide by the views in the main folder.
