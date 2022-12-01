export default async function () {
    // The unit tests expect that events and other objects are persisted to
    // ClickHouse, on which we make assertions. This starts the ClickHouse Kafka
    // consumer which will push events etc. into ClickHouse.
    //
    // Here we assume that there was a consumer and producer connected, which
    // need to be disconnected to enable a clean exit of the Jest test runner.

    await globalThis.clickHouseConsumer.disconnect()
    await globalThis.producer.disconnect()
}
