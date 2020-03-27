Run the following in the root of the posthog folder to install the chart and run posthog with an internal database

```shell script
  helm install -f chart/values-local.yaml posthog ./chart
```

When using a managed database, don't forget to change `databaseURL`!