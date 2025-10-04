# Testing Databricks batch exports

To enable testing for Databricks batch exports we require:

1. A Databricks account
2. A catalog inside the account for testing
3. A service principal with required permissions:
    - access to said catalog:
        - this can be granted using, for example, ``GRANT ALL PRIVILEGES ON CATALOG batch_export_tests TO `batch export testers`;``
    - be able to read files from volumes
        - this can be granted using, for example, ``GRANT SELECT ON ANY FILE TO `batch export testers`;``
4. Machine-to-machine OAuth2 credentials (client id and client secret) for said service principal
    - You can find more details on authentication in the [Databricks documentation](https://docs.databricks.com/aws/en/dev-tools/python-sql-connector#oauth-machine-to-machine-m2m-authentication)

The tests can then be run using a command such as the following:

```bash
DEBUG=1 DATABRICKS_SERVER_HOSTNAME=my-host.cloud.databricks.com DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/my-warehouse DATABRICKS_CLIENT_ID=my-client-id DATABRICKS_CLIENT_SECRET=my-client-secret pytest products/batch_exports/backend/tests/temporal/destinations/databricks/test_workflow.py
```
