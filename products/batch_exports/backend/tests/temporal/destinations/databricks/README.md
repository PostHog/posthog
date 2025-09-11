# Testing Databricks batch exports

To enable testing for Databricks batch exports we require:

1. A Databricks account
2. A catalog inside the account for testing
3. A service principal with required permissions:
    - access to said catalog:
        - this can be granted using, for example, `GRANT ALL PRIVILEGES ON CATALOG batch_export_tests TO ``batch export testers``;`
    - be able to read files from volumes
        - this can be granted using, for example, `GRANT SELECT ON ANY FILE TO ``batch export testers``;`
4. Machine-to-machine OAuth2 credentials for said service account
