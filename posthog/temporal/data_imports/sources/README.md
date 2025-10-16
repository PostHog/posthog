# Adding a new source to data pipelines

Adding a new source should be pretty simple. We've refactored the sources so that you need to only add your source logic and update a small number of other files. Simply copy the source template file and address all the TODOs in that file in order.

```sh
mkdir -p posthog/temporal/data_imports/sources/{SOURCE_NAME}
cp posthog/temporal/data_imports/sources/source.template posthog/temporal/data_imports/sources/{SOURCE_NAME}/source.py
```

## Source fields

The fields shown on the frontend are all backend driven. We have a collection of 6 field types available to collect info such as API keys, auth logins, and file uploads.

The frontend logic for rendering the below fields can be found in `frontend/src/scenes/data-warehouse/external/forms/SourceForm.tsx`.

All of the below are defined in `posthog/schema.py` with a union of them defined as `FieldType` in `posthog/temporal/data_imports/sources/common/base.py`. Check out the other sources for examples of how we implement these.

#### `SourceFieldInputConfig`

This is your basic input field. You can set a `placeholder`, whether it's `required`, and the `type` (text, email, number, textarea, etc). This renders as a `<LemonInput />`.

#### `SourceFieldSwitchGroupConfig`

This renders a toggle that when enabled will render a group of sub-fields. This is useful when you may have optional settings that a user can turn on/off. This field has a `default` that can be set, along with a list of `fields` that will be shown when it's enabled. The field itself will be rendered as a `<LemonSwitch />`

#### `SourceFieldSelectConfig`

This is a select input (drop down select) field. You can define the `defaultValue`, as well as a list of `options`. Options can be plain label/value combination, or you can also add a `fields` list to the option to display sub-fields when an option is selected. This field also supports a `converter` value that can convert values from the options into a particular type (e.g. convert string values to bools).

#### `SourceFieldOauthConfig`

Sources support adding oauth authentication methods for sources. This is backed by the `Integration` model allowing for easy oauth connections. Define the `kind` of the integration along with whether it's `required` and a given `label`.

For detailed setup instructions, see the [OAuth Configuration](#oauth-configuration) section below.

#### `SourceFieldFileUploadConfig`

This allows users to upload files to us. Currently we only support JSON files with either an allow list of keys or an allow-all option - set this via the `fileFormat` option. Define the allowed keys as either a list of keys on `keys` (e.g. `["key_1", "key_2"]`) or to allow all keys use just `"*"`.

#### `SourceFieldSSHTunnelConfig`

The SSH tunnel config is a slightly special field type. It tells the frontend to render a selection of fields to collect SSH tunneling info. We use this to allow users to connect to database sources behind a bastion host (mainly if they can't or don't want to expose their database to the public internet). There's very little you need to do with this field - but it will add a `ssh_tunnel: SSHTunnel` field to your config class which come with a bunch of helper methods for easy connections

## Source logic

Sources should return a `SourceResponse` class. This informs the pipeline on how to import data from your source and provides a bunch of helpers to ensure the pipeline is efficient.

We have a bunch of examples already in the sources directory of how we build up this `SourceResponse` class, and so I'd recommend checking some of them out first.

`items`: This is what the pipeline iterates over to pull items from your source. Some rules for the iterator:

- It should return items as either `dict`, `list[dict]`, or a `pyarrow.Table` object. For sources with a defined schema that we can pull, such as a database table, we prefer the source returned a `pyarrow.Table` object with a well defined schema
- It's okay to yield items one at a time if that's how the source logic is handled (excluding pyarrow tables). The pipeline will buffer the incoming items until it has a reasonable amount before running the pipeline over the dataset
- If you are returning a `pyarrow.Table` object, then please make sure that there is a reasonable limit on how many rows that get held in memory. For most of our sources, we limit this to either 200 MiB or 5,000 rows.

We have some helper methods for returning a `pyarrow.Table` from the source, such as `table_from_iterator()` and `table_from_py_list()` from `posthog/temporal/data_imports/pipelines/pipeline/utils.py`. The pipeline will ultimately convert everything to a `pyarrow.Table` using these methods

#### `primary_keys`

For a source to support incremental syncing, the `SourceResponse` must have primary keys set - these are the unique fields that the rows will be merged on. If the source has a unique `id` field, then you'd set `primary_keys=["id"]`. If the source requires multiple fields to create a unique composite, then you'd add all of these to the list, e.g. `primary_keys=["user_id", "date", "page_url"]`

#### `sort_mode`

Which direction the source scrolls incremental data, either ascending (the default and preferred sort mode) or descending. Majority of APIs will support ascending sorted responses, but if they only support descending then this will need to be set.

We store both a `db_incremental_field_last_value` and `db_incremental_field_earliest_value` value - these represent that max/min of the data we've read from the source and processed by the pipeline. When using a `descending` sort mode, we recommend that your source also scrolls for any earlier rows than `db_incremental_field_earliest_value` before trying to scroll for more recent rows. A great example of this is the Stripe source.

#### `rows_to_sync`

If you can request how many rows are about to be imported (this is usually more the case with database sources as opposed to API backed sources), then returning this value allows the pipeline to ensure the users org has a high enough billing limit to sync the data. We recommend setting this when possible.

#### `has_duplicate_primary_keys`

Also optional, setting this to `True` will stop the pipeline from syncing any data and give the user feedback that they can't sync until they no longer have duplicate primary keys. Again, this is more of a problem with database sources than API backed sources. But, the point of this is to ensure we don't try to merge incremental data with duplicate merge keys as this blows up the memory usage of our pods and kills them with OOM errors.

### Partitioning

We support and recommend using partitioning for all new sources. Partitioning allows us to write the source rows into sub-folders in S3 to allow for efficient merging of data on subsequent pipeline runs. The whole point of this is to reduce the amount of data we're loading into memory on the pods when syncing incremental tables.

We have several partitioning modes - `md5`, `numerical`, and `datetime`:

`md5` will bucket rows based on a md5 hash of the primary key fields. This is the least efficient partitioning as it means we're typically hitting every partition when syncing a new dataset, though it's still memory efficient as we only merge a single partition at a time, the partitions can grow in size over time and become too large (this is due to there needing to be a finite set of partitions set on the first sync).

`numerical` will bucket based on a numerical primary key, such as an incrementing `id` field. Each partition will have a set number of rows and the partition count will grow over time.

`datetime` will bucket based on a datetime field. We truncate the datetime down to the `month`. This can be overridden to be partitioned by `day` for high volume tables though.

For database sources, we recommend setting `partition_count` and `partition_size`. For API backed sources, we recommend setting `partition_keys`, `partition_mode`, and `partition_format`.

- `partition_count` refers to how many partitions there should exist for the `md5` mode
- `partition_size` refers to how many rows should be bucketed together in a single partition for the `numerical` mode

## OAuth Configuration

If your source uses OAuth (SourceFieldOauthConfig):

1. **Environment Variables**: Add to your environment:

    ```bash
    YOUR_SOURCE_CLIENT_ID=your_client_id
    YOUR_SOURCE_CLIENT_SECRET=your_client_secret
    ```

    **If your integration doesn't exist yet**, add it to `posthog/settings/integrations.py`:

    ```python
    YOUR_SOURCE_CLIENT_ID = get_from_env("YOUR_SOURCE_CLIENT_ID", "")
    YOUR_SOURCE_CLIENT_SECRET = get_from_env("YOUR_SOURCE_CLIENT_SECRET", "")
    ```

2. **Integration Kind**: Add your integration to `posthog/models/integration.py`:

    **a) Add to `IntegrationKind` enum:**

    ```python
    class IntegrationKind(models.TextChoices):
        # ... existing integrations ...
        YOUR_SOURCE = "your-source"
    ```

    **b) Add to `OauthIntegration.supported_kinds` list:**

    ```python
    supported_kinds = [
        # ... existing kinds ...
        "your-source",
    ]
    ```

    **c) Add OAuth config in `oauth_config_for_kind()` method:**

    ```python
    elif kind == "your-source":
        if not settings.YOUR_SOURCE_CLIENT_ID or not settings.YOUR_SOURCE_CLIENT_SECRET:
            raise NotImplementedError("Your Source app not configured")

        return OauthConfig(
            authorize_url="https://your-service.com/oauth/authorize",
            token_url="https://your-service.com/oauth/token",
            client_id=settings.YOUR_SOURCE_CLIENT_ID,
            client_secret=settings.YOUR_SOURCE_CLIENT_SECRET,
            scope="your required scopes",
            id_path="id",
            name_path="name",
        )
    ```

3. **Redirect URI**: Configure in external service:

    ```text
    https://localhost:8010/integrations/your-kind/callback
    ```

## Testing Your Source Locally

1. **Start PostHog**: `DEBUG=1 ./bin/start`
2. **Navigate to**: Data Warehouse → New Source
3. **Test OAuth flow**: Click "Connect with [Your Service]"
4. **Test form**: Verify all fields render correctly
5. **Test credentials**: Check validation works
6. **Test schema discovery**: Verify schemas are detected

**Common Issues**:

- "Kind not configured" → Check environment variables are set
- Source not listed → Verify step 8 (source registration)
- Frontend errors → Run `pnpm schema:build`

## Mixins

We have a handful of mixins available for your source classes. Add these to your inherited classes to get some extra functionality for handling certain fields. These can be found `posthog/temporal/data_imports/sources/common/mixins.py`

#### `SSHTunnelMixin`

Provides a `with_ssh_tunnel()` context that opens a tunnel to a target and provides you with a host/port to connect to with your source.

We also expose a `make_ssh_tunnel_func()` that does the same as the above, but instead returns a function to be passed to open the tunnel at a later time. This is helpful if your source logic doesn't actually live in your source class directly.

#### `OAuthMixin`

Provides a simple `get_oauth_integration()` method to pull the `Integration` object out of the DB for you

#### `ValidateDatabaseHostMixin`

Provides `is_database_host_valid()` to validate that the source isn't trying to access local IP addresses in our internal VPC on AWS (unless if the user is using a SSH tunnel).
