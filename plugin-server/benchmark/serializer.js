import protobuf from 'protobufjs'

let EventMessage = null

// Load protobuf schema
async function loadProtobuf() {
    if (!EventMessage) {
        const root = await protobuf.load('./event.proto')
        EventMessage = root.lookupType('posthog.Event')
    }
    return EventMessage
}

export class Serializer {
    constructor(format = 'json') {
        this.format = format
    }

    async serialize(event) {
        if (this.format === 'protobuf') {
            const EventMessage = await loadProtobuf()
            const message = EventMessage.create(event)
            return EventMessage.encode(message).finish()
        } else {
            return JSON.stringify(event)
        }
    }

    async deserialize(data) {
        if (this.format === 'protobuf') {
            const EventMessage = await loadProtobuf()
            const decoded = EventMessage.decode(data)
            return EventMessage.toObject(decoded)
        } else {
            // eslint-disable-next-line no-restricted-syntax
            return JSON.parse(data)
        }
    }

    async deserializeBatch(dataArray) {
        if (this.format === 'protobuf') {
            const EventMessage = await loadProtobuf()
            return dataArray.map((data) => {
                const decoded = EventMessage.decode(data)
                return EventMessage.toObject(decoded)
            })
        } else {
            // eslint-disable-next-line no-restricted-syntax
            return dataArray.map((data) => JSON.parse(data))
        }
    }
}
