import { LemonDivider, LemonModal, LemonModalProps, LemonSwitch, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { streamModalLogic } from './streamModalLogic'

interface StreamModalProps extends LemonModalProps {}

export default function StreamModal(props: StreamModalProps): JSX.Element {
    const { formattedStreamOptions, streamOptionsLoading } = useValues(streamModalLogic)
    const { updateStreamOption } = useActions(streamModalLogic)

    return (
        <LemonModal
            {...props}
            title="Data Source Streams"
            description={
                'Select the streams from the source you want to sync to PostHog. These streams will be available after the next sync occurs'
            }
        >
            <div className="mt-2 pb-2 rounded overflow-y-auto" style={{ maxHeight: 300 }}>
                {streamOptionsLoading ? (
                    <Spinner />
                ) : (
                    formattedStreamOptions.map((streamRow, index) => (
                        <>
                            {index > 0 && <LemonDivider />}
                            <StreamRow
                                key={streamRow.streamName}
                                streamName={streamRow.streamName}
                                selected={streamRow.selected}
                                onChange={(newChecked) => updateStreamOption(streamRow.streamName, newChecked)}
                            />
                        </>
                    ))
                )}
            </div>
        </LemonModal>
    )
}

interface StreamRowProps {
    streamName: string
    selected: boolean
    onChange: (newChecked: boolean) => void
}

function StreamRow({ streamName, selected, onChange }: StreamRowProps): JSX.Element {
    return (
        <div className="flex items-center justify-between mt-2 pl-2 h-8">
            <span>{streamName}</span>
            <LemonSwitch checked={selected} onChange={onChange} />
        </div>
    )
}
