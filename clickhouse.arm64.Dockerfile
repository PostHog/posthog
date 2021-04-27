# To build: docker build -t clickhouse/arm64:latest -f clickhouse.arm64.Dockerfile .
FROM arm64v8/ubuntu

#ADD https://builds.clickhouse.tech/master/macos/clickhouse /clickhouse
ADD https://builds.clickhouse.tech/master/aarch64/clickhouse /clickhouse
RUN chmod a+x /clickhouse
RUN apt-get update
RUN apt-get install -y vim python3.8
RUN yes '' | ./clickhouse install --user root --group root
COPY ee/config.clickhouse.xml /etc/clickhouse-server/config.xml
COPY ee/idl /var/lib/clickhouse/format_schemas/
RUN rm ./clickhouse
CMD ["clickhouse", "server", "-C", "/etc/clickhouse-server/config.xml"]

EXPOSE 9000 9440 8123 9009