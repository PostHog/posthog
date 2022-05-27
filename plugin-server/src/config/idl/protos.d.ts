import * as $protobuf from 'protobufjs'
/** Properties of an Event. */
export interface IEvent {
    /** Event uuid */
    uuid?: string | null

    /** Event event */
    event?: string | null

    /** Event properties */
    properties?: string | null

    /** Event timestamp */
    timestamp?: string | null

    /** Event team_id */
    team_id?: number | Long | null

    /** Event distinct_id */
    distinct_id?: string | null

    /** Event created_at */
    created_at?: string | null

    /** Event elements_chain */
    elements_chain?: string | null

    /** Event proto_created_at */
    proto_created_at?: google.protobuf.ITimestamp | null

    /** Event proto_timestamp */
    proto_timestamp?: google.protobuf.ITimestamp | null
}

/** Represents an Event. */
export class Event implements IEvent {
    /**
     * Constructs a new Event.
     * @param [properties] Properties to set
     */
    constructor(properties?: IEvent)

    /** Event uuid. */
    public uuid: string

    /** Event event. */
    public event: string

    /** Event properties. */
    public properties: string

    /** Event timestamp. */
    public timestamp: string

    /** Event team_id. */
    public team_id: number | Long

    /** Event distinct_id. */
    public distinct_id: string

    /** Event created_at. */
    public created_at: string

    /** Event elements_chain. */
    public elements_chain: string

    /** Event proto_created_at. */
    public proto_created_at?: google.protobuf.ITimestamp | null

    /** Event proto_timestamp. */
    public proto_timestamp?: google.protobuf.ITimestamp | null

    /**
     * Creates a new Event instance using the specified properties.
     * @param [properties] Properties to set
     * @returns Event instance
     */
    public static create(properties?: IEvent): Event

    /**
     * Encodes the specified Event message. Does not implicitly {@link Event.verify|verify} messages.
     * @param message Event message or plain object to encode
     * @param [writer] Writer to encode to
     * @returns Writer
     */
    public static encode(message: IEvent, writer?: $protobuf.Writer): $protobuf.Writer

    /**
     * Encodes the specified Event message, length delimited. Does not implicitly {@link Event.verify|verify} messages.
     * @param message Event message or plain object to encode
     * @param [writer] Writer to encode to
     * @returns Writer
     */
    public static encodeDelimited(message: IEvent, writer?: $protobuf.Writer): $protobuf.Writer

    /**
     * Decodes an Event message from the specified reader or buffer.
     * @param reader Reader or buffer to decode from
     * @param [length] Message length if known beforehand
     * @returns Event
     * @throws {Error} If the payload is not a reader or valid buffer
     * @throws {$protobuf.util.ProtocolError} If required fields are missing
     */
    public static decode(reader: $protobuf.Reader | Uint8Array, length?: number): Event

    /**
     * Decodes an Event message from the specified reader or buffer, length delimited.
     * @param reader Reader or buffer to decode from
     * @returns Event
     * @throws {Error} If the payload is not a reader or valid buffer
     * @throws {$protobuf.util.ProtocolError} If required fields are missing
     */
    public static decodeDelimited(reader: $protobuf.Reader | Uint8Array): Event

    /**
     * Verifies an Event message.
     * @param message Plain object to verify
     * @returns `null` if valid, otherwise the reason why it is not
     */
    public static verify(message: { [k: string]: any }): string | null

    /**
     * Creates an Event message from a plain object. Also converts values to their respective internal types.
     * @param object Plain object
     * @returns Event
     */
    public static fromObject(object: { [k: string]: any }): Event

    /**
     * Creates a plain object from an Event message. Also converts values to other types if specified.
     * @param message Event
     * @param [options] Conversion options
     * @returns Plain object
     */
    public static toObject(message: Event, options?: $protobuf.IConversionOptions): { [k: string]: any }

    /**
     * Converts this Event to JSON.
     * @returns JSON object
     */
    public toJSON(): { [k: string]: any }
}

/** Namespace google. */
export namespace google {
    /** Namespace protobuf. */
    namespace protobuf {
        /** Properties of a Timestamp. */
        interface ITimestamp {
            /** Timestamp seconds */
            seconds?: number | Long | null

            /** Timestamp nanos */
            nanos?: number | null
        }

        /** Represents a Timestamp. */
        class Timestamp implements ITimestamp {
            /**
             * Constructs a new Timestamp.
             * @param [properties] Properties to set
             */
            constructor(properties?: google.protobuf.ITimestamp)

            /** Timestamp seconds. */
            public seconds: number | Long

            /** Timestamp nanos. */
            public nanos: number

            /**
             * Creates a new Timestamp instance using the specified properties.
             * @param [properties] Properties to set
             * @returns Timestamp instance
             */
            public static create(properties?: google.protobuf.ITimestamp): google.protobuf.Timestamp

            /**
             * Encodes the specified Timestamp message. Does not implicitly {@link google.protobuf.Timestamp.verify|verify} messages.
             * @param message Timestamp message or plain object to encode
             * @param [writer] Writer to encode to
             * @returns Writer
             */
            public static encode(message: google.protobuf.ITimestamp, writer?: $protobuf.Writer): $protobuf.Writer

            /**
             * Encodes the specified Timestamp message, length delimited. Does not implicitly {@link google.protobuf.Timestamp.verify|verify} messages.
             * @param message Timestamp message or plain object to encode
             * @param [writer] Writer to encode to
             * @returns Writer
             */
            public static encodeDelimited(
                message: google.protobuf.ITimestamp,
                writer?: $protobuf.Writer
            ): $protobuf.Writer

            /**
             * Decodes a Timestamp message from the specified reader or buffer.
             * @param reader Reader or buffer to decode from
             * @param [length] Message length if known beforehand
             * @returns Timestamp
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            public static decode(reader: $protobuf.Reader | Uint8Array, length?: number): google.protobuf.Timestamp

            /**
             * Decodes a Timestamp message from the specified reader or buffer, length delimited.
             * @param reader Reader or buffer to decode from
             * @returns Timestamp
             * @throws {Error} If the payload is not a reader or valid buffer
             * @throws {$protobuf.util.ProtocolError} If required fields are missing
             */
            public static decodeDelimited(reader: $protobuf.Reader | Uint8Array): google.protobuf.Timestamp

            /**
             * Verifies a Timestamp message.
             * @param message Plain object to verify
             * @returns `null` if valid, otherwise the reason why it is not
             */
            public static verify(message: { [k: string]: any }): string | null

            /**
             * Creates a Timestamp message from a plain object. Also converts values to their respective internal types.
             * @param object Plain object
             * @returns Timestamp
             */
            public static fromObject(object: { [k: string]: any }): google.protobuf.Timestamp

            /**
             * Creates a plain object from a Timestamp message. Also converts values to other types if specified.
             * @param message Timestamp
             * @param [options] Conversion options
             * @returns Plain object
             */
            public static toObject(
                message: google.protobuf.Timestamp,
                options?: $protobuf.IConversionOptions
            ): { [k: string]: any }

            /**
             * Converts this Timestamp to JSON.
             * @returns JSON object
             */
            public toJSON(): { [k: string]: any }
        }
    }
}
