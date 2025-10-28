---
title: Working with data warehouse
sidebar: Docs
showTitle: true
---

This is an internal guide to setting up and working with the data warehouse for PostHog engineers. If you're a PostHog user, check out our [data warehouse docs](/docs/data-warehouse) instead.

## Adding a new source

Looking to add a new source to data warehouse? [We have a detailed guide in the codebase](https://github.com/PostHog/posthog/blob/master/posthog/temporal/data_imports/sources/README.md). 

> If you're a customer of PostHog Cloud and are looking to import data into your project, then you're likely looking for [this section of the docs instead](/docs/cdp/sources)


## Importing your local Postgres instance

1. Head to the [new source flow](http://localhost:8010/project/pipeline/new/source) in your local app, hit the link button next to Postgres
2. Use the following settings:
    1. host = 127.0.0.1
    2. port = 5432
    3. database = posthog
    4. user = posthog
    5. password = posthog
    6. schema = public
3. Hit next, then select which tables you'd like to import. [More info on the sync types can be found here](/docs/cdp/sources#incremental-vs-append-only-vs-full-table)
4. Hit next and finish the import - `temporal-worker-data-warehouse` will then import the data into your local MinIO instance

## Accessing MinIO

All your data warehouse data is stored in your local MinIO instance. You can view all the files by going to `http://localhost:19001/` and using the username `object_storage_root_user` and password `object_storage_root_password`. There should be a `data-warehouse` bucket that has a separate folder for each table you sync. 

## Setting up a MySQL source

If you want to set up a local MySQL database as a source for the data warehouse, there are a few extra set up steps you'll need to complete:

First, install MySQL:

```bash
brew install mysql
brew services start mysql
```

Once MySQL is installed, create a database and table, insert a row, and create a user who can connect to it:

```bash
mysql -u root
```

```sql runInPostHog=false
CREATE DATABASE posthog_dw_test;
CREATE TABLE IF NOT EXISTS payments (id INT AUTO_INCREMENT PRIMARY KEY, timestamp DATETIME, distinct_id VARCHAR(255), amount DECIMAL(10,2));

INSERT INTO payments (timestamp, distinct_id, amount) VALUES (NOW(), 'testuser@example.com', 99.99);

CREATE USER 'posthog'@'%' IDENTIFIED BY 'posthog';
GRANT ALL PRIVILEGES ON posthog_dw_test.* TO 'posthog'@'%';
FLUSH PRIVILEGES;
```

To verify everything is working as expected:
1. Navigate to "Data pipeline" in the PostHog application.
2. Create a new MySQL source using the settings above (username and password both being `posthog`)
3. Once the source is created, click on the "MySQL" item. In the schemas table, click on the triple dot menu and select the "Reload" option.

After the job runs, clicking on the synced table name should take you to your data.


## Working with a MS SQL source

You'll need to install MS SQL drivers for the PostHog app to connect to a MS SQL database. Learn the entire process in [posthog/warehouse/README.md](https://github.com/PostHog/posthog/blob/master/posthog/warehouse/README.md). Without the drivers, you'll get the following error when connecting a SQL database to data warehouse:

```
symbol not found in flat namespace '_bcp_batch'
```
