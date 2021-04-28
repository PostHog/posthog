# To build: docker build -t clickhouse/arm64:latest -f clickhouse.arm64.Dockerfile .
FROM arm64v8/ubuntu

RUN apt-get update
RUN apt-get install -y openssl vim
ADD https://builds.clickhouse.tech/master/aarch64/clickhouse /clickhouse
RUN chmod a+x /clickhouse
RUN yes '' | ./clickhouse install --user root --group root
COPY ee/config.clickhouse.xml /etc/clickhouse-server/config.xml
COPY ee/idl /var/lib/clickhouse/format_schemas/
RUN rm ./clickhouse
RUN openssl req -subj "/CN=localhost" -new -newkey rsa:2048 -days 365 -nodes -x509 -keyout /etc/clickhouse-server/server.key -out /etc/clickhouse-server/server.crt
CMD ["clickhouse", "server", "-C", "/etc/clickhouse-server/config.xml"]

EXPOSE 9000 9440 8123 9009