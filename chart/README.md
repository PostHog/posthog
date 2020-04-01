# PostHog

[PostHog](https://posthog.io/) is a cross-platform crash reporting and aggregation platform.

## TL;DR;

```console
$ helm install ./chart
```

## Introduction

This chart bootstraps a [PostHog](https://posthog.io/) deployment on a [Kubernetes](http://kubernetes.io) cluster using the [Helm](https://helm.sh) package manager.

It also optionally packages [PostgreSQL](https://github.com/kubernetes/charts/tree/master/stable/postgresql) which is required for PostHog.

## Prerequisites

- Kubernetes 1.4+ with Beta APIs enabled
- helm >= v3
- PV provisioner support in the underlying infrastructure (with persistence storage enabled)

## Installing the Chart

To install the chart with the release name `my-release`:

```console
$ helm install --name my-release ./chart
```

The command deploys PostHog on the Kubernetes cluster in the default configuration. The [configuration](#configuration) section lists the parameters that can be configured during installation.

> **Tip**: List all releases using `helm list`

## Uninstalling the Chart

To uninstall/delete the `my-release` deployment:

```console
$ helm delete my-release
```

The command removes all the Kubernetes components associated with the chart and deletes the release.

> **Warning**: Jobs are not deleted automatically. They need to be manually deleted

```console
$ kubectl delete job/posthog-migrate
```

## Configuration

The following table lists the configurable parameters of the PostHog chart and their default values.

Dependent charts can also have values overwritten. Preface values with postgresql.* or redis.*
=======
Parameter                                            | Description                                                                                                | Default
:--------------------------------------------------- | :--------------------------------------------------------------------------------------------------------- | :---------------------------------------------------
`image.repository`                                   | PostHog image                                                                                              | `posthog/posthog`
`image.tag`                                          | PostHog image tag                                                                                          | `latest`
`image.pullPolicy`                                   | Image pull policy                                                                                          | `Always`
`image.imagePullSecrets`                             | Specify image pull secrets                                                                                 | `[]`
`posthogSecret`                                      | Specify SECRET_KEY. If isn't specified it will be generated automatically.                                 | `nil`
`web.podAnnotations`                                 | Web pod annotations                                                                                        | `{}`
`web.podLabels`                                      | Web pod extra labels                                                                                       | `{}`
`web.replicacount`                                   | Amount of web pods to run                                                                                  | `1`
`web.resources.limits`                               | Web resource limits                                                                                        | `{cpu: 500m, memory: 500Mi}`
`web.resources.requests`                             | Web resource requests                                                                                      | `{cpu: 300m, memory: 300Mi}`
`web.env`                                            | Additional web environment variables                                                                       | `[]`
`web.nodeSelector`                                   | Node labels for web pod assignment                                                                         | `{}`
`web.affinity`                                       | Affinity settings for web pod assignment                                                                   | `{}`
`web.schedulerName`                                  | Name of an alternate scheduler for web pod                                                                 | `nil`
`web.tolerations`                                    | Toleration labels for web pod assignment                                                                   | `[]`
`web.livenessProbe.failureThreshold`                 | The liveness probe failure threshold                                                                       | `5`
`web.livenessProbe.initialDelaySeconds`              | The liveness probe initial delay seconds                                                                   | `50`
`web.livenessProbe.periodSeconds`                    | The liveness probe period seconds                                                                          | `10`
`web.livenessProbe.successThreshold`                 | The liveness probe success threshold                                                                       | `1`
`web.livenessProbe.timeoutSeconds`                   | The liveness probe timeout seconds                                                                         | `2`
`web.readinessProbe.failureThreshold`                | The readiness probe failure threshold                                                                      | `10`
`web.readinessProbe.initialDelaySeconds`             | The readiness probe initial delay seconds                                                                  | `50`
`web.readinessProbe.periodSeconds`                   | The readiness probe period seconds                                                                         | `10`
`web.readinessProbe.successThreshold`                | The readiness probe success threshold                                                                      | `1`
`web.readinessProbe.timeoutSeconds`                  | The readiness probe timeout seconds                                                                        | `2`
`web.priorityClassName`                              | The priorityClassName on web deployment                                                                    | `nil`
`web.hpa.enabled`                                    | Boolean to create a HorizontalPodAutoscaler for web deployment                                             | `false`
`web.hpa.cputhreshold`                               | CPU threshold percent for the web HorizontalPodAutoscaler                                                  | `60`
`web.hpa.minpods`                                    | Min pods for the web HorizontalPodAutoscaler                                                               | `1`
`web.hpa.maxpods`                                    | Max pods for the web HorizontalPodAutoscaler                                                               | `10`
`service.type`                                       | Kubernetes service type                                                                                    | `LoadBalancer`
`service.name`                                       | Kubernetes service name                                                                                    | `posthog`
`service.externalPort`                               | Kubernetes external service port                                                                           | `8000`
`service.internalPort`                               | Kubernetes internal service port                                                                           | `8000`
`service.annotations`                                | Service annotations                                                                                        | `{}`
`service.nodePort`                                   | Kubernetes service NodePort port                                                                           | Randomly chosen by Kubernetes
`service.loadBalancerSourceRanges`                   | Allow list for the load balancer                                                                           | `nil`
`ingress.enabled`                                    | Enable ingress controller resource                                                                         | `false`
`ingress.annotations`                                | Ingress annotations                                                                                        | `{}`
`ingress.hostname`                                   | URL to address your PostHog installation                                                                   | `posthog.local`
`ingress.path`                                       | path to address your PostHog installation                                                                  | `/`
`ingress.tls`                                        | Ingress TLS configuration                                                                                  | `[]`
`postgresql.enabled`                                 | Deploy postgres server (see below)                                                                         | `true`
`postgresql.postgresqlDatabase`                      | Postgres database name                                                                                     | `posthog`
`postgresql.postgresqlUsername`                      | Postgres username                                                                                          | `postgres`
`postgresql.postgresqlHost`                          | External postgres host                                                                                     | `nil`
`postgresql.postgresqlPassword`                      | External/Internal postgres password                                                                        | `postgres`
`postgresql.postgresqlPort`                          | External postgres port                                                                                     | `5432`
`postgresql.existingSecret`                          | Name of existing secret to use for the PostgreSQL password                                                 | `nil`
`postgresql.existingSecretKey`                       | Key to get from the `postgresql.existingSecret` secret                                                     | `postgresql-password`                                                                               | `nil`
`metrics.enabled`                                    | Start an exporter for posthog metrics                                                                      | `false`
`metrics.nodeSelector`                               | Node labels for metrics pod assignment                                                                     | `{}`
`metrics.tolerations`                                | Toleration labels for metrics pod assignment                                                               | `[]`
`metrics.affinity`                                   | Affinity settings for metrics pod                                                                          | `{}`
`metrics.schedulerName`                              | Name of an alternate scheduler for metrics pod                                                             | `nil`
`metrics.podLabels`                                  | Labels for metrics pod                                                                                     | `nil`
`metrics.resources`                                  | Metrics resource requests/limit                                                                            | `{}`
`metrics.service.type`                               | Kubernetes service type for metrics service                                                                | `ClusterIP`
`metrics.service.labels`                             | Additional labels for metrics service                                                                      | `{}`
`metrics.image.repository`                           | Metrics exporter image repository                                                                          | `prom/statsd-exporter`
`metrics.image.tag`                                  | Metrics exporter image tag                                                                                 | `v0.10.5`
`metrics.image.PullPolicy`                           | Metrics exporter image pull policy                                                                         | `IfNotPresent`
`metrics.serviceMonitor.enabled`                     | if `true`, creates a Prometheus Operator ServiceMonitor (also requires `metrics.enabled` to be `true`)     | `false`
`metrics.serviceMonitor.namespace`                   | Optional namespace which Prometheus is running in                                                          | `nil`
`metrics.serviceMonitor.interval`                    | How frequently to scrape metrics (use by default, falling back to Prometheus' default)                     | `nil`
`metrics.serviceMonitor.selector`                    | Default to kube-prometheus install (CoreOS recommended), but should be set according to Prometheus install | `{ prometheus: kube-prometheus }`
`hooks.affinity`                                     | Affinity settings for hooks pods                                                                           | `{}`
`hooks.migrate.resources.limits`                     | Hook job resource limits                                                                                   | `{memory: 1000Mi}`
`hooks.migrate.resources.requests`                   | Hook job resource requests                                                                                 | `{memory: 1000Mi}`
`serviceAccount.name`                                | name of the ServiceAccount to be used by access-controlled resources                                       | autogenerated
`serviceAccount.create`                              | Configures if a ServiceAccount with this name should be created                                            | `true`
`serviceAccount.annotations`                         | Configures annotation for the ServiceAccount                                                               | `{}`

Dependent charts can also have values overwritten. Preface values with "postgresql."

Specify each parameter using the `--set key=value[,key=value]` argument to `helm install`. For example,

```console
$ helm install --name my-release \
  --set persistence.enabled=false,email.host=email \
    ./chart
```

Alternatively, a YAML file that specifies the values for the above parameters can be provided while installing the chart. For example,

```console
$ helm install --name my-release -f my-values.yaml ./chart
```

## PostgresSQL

By default, PostgreSQL is installed as part of the chart. To use an external PostgreSQL server set `postgresql.enabled` to `false` and then set `postgresql.postgresHost` and `postgresql.postgresqlPassword`. The other options (`postgresql.postgresqlDatabase`, `postgresql.postgresqlUsername` and `postgresql.postgresqlPort`) may also want changing from their default values.

To avoid issues when upgrading this chart, provide `postgresql.postgresqlPassword` for subsequent upgrades. This is due to an issue in the PostgreSQL chart where password will be overwritten with randomly generated passwords otherwise. See https://github.com/helm/charts/tree/master/stable/postgresql#upgrade for more detail.

## Ingress

This chart provides support for Ingress resource. If you have an available Ingress Controller such as Nginx or Traefik you maybe want to set `ingress.enabled` to true and choose an `ingress.hostname` for the URL. Then, you should be able to access the installation using that address.

