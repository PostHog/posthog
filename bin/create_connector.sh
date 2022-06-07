#!/bin/bash

# Check Kafka Connect is available at all
while true; do
  KAFKA_CONNECT=$(curl -sb -I 'http://localhost:8083')
  if [[ $KAFKA_CONNECT =~ .*version.* ]]; then
    break
  fi

  echo 'Waiting for Kafka Connect...' && sleep 1
done

while true; do
  RESULT=$(# Creates a Kafka Connect S3 Sink for session recordings
    curl -X PUT http://localhost:8083/connectors/session-recordings/config \
    -H "Content-Type: application/json" \
    -d '{
        "name": "session-recordings",
        "connector.class": "io.confluent.connect.s3.S3SinkConnector",
        "topics": "session-recordings",
        "key.converter": "org.apache.kafka.connect.converters.ByteArrayConverter",
        "value.converter": "org.apache.kafka.connect.json.JsonConverter",
        "value.converter.schemas.enable": true,
        "partitioner.class": "io.confluent.connect.storage.partitioner.FieldPartitioner",
        "partition.field.name": "team_id,session_id,window_id",
        "format.class": "io.confluent.connect.s3.format.json.JsonFormat",
        "s3.bucket.name": "posthog",
        "s3.region": "us-east-1",
        "storage.class": "io.confluent.connect.s3.storage.S3Storage",
        "store.url": "http://object-storage:19000",
        "topics.dir": "session-recordings",
        "flush.size": 10,
        "s3.part.size": 5242880
    }'
    )

    if [[ $RESULT =~ .*session-recordings.* ]]; then
      echo "✅ session recordings connector is created"
      break
    fi

    echo 'Creating session recordings connector...' && sleep 1
done

