import { actions, kea, key, path, props, reducers, selectors } from 'kea'

export type TimestampFormat = 'absolute' | 'relative'
export type TZLabelLogicProps = {
    logicKey?: string
    defaultTimestampFormat?: TimestampFormat
}
export const tzLabelLogic = kea([
    props({ defaultTimestampFormat: 'relative' as TimestampFormat } as TZLabelLogicProps),
    key(({ logicKey }: TZLabelLogicProps) => logicKey ?? 'global'),
    path((key) => ['src', 'lib', 'components', 'tzLabelLogic', key]),
    actions({
        setTimestampFormatChoice: (timestampFormatChoice: TimestampFormat) => ({ timestampFormatChoice }),
    }),

    reducers({
        timestampFormatChoice: [
            null as TimestampFormat | null,
            { persist: true },
            {
                setTimestampFormat: (_, { timestampFormat }) => timestampFormat,
            },
        ],
    }),

    selectors({
        timestampFormat: [
            (s, p) => [s.timestampFormatChoice, p.defaultTimestampFormat],
            (timestampFormatChoice, defaultTimestampFormat): TimestampFormat => {
                return timestampFormatChoice ?? defaultTimestampFormat
            },
        ],
        formatting: [
            (s) => [s.timestampFormat],
            (timestampFormat): { date: string; time: string } | null => {
                if (timestampFormat === 'relative') {
                    return null
                }

                return {
                    date: 'MMMM DD,YYYY',
                    time: 'h:mm:ss',
                }
            },
        ],
    }),
])
