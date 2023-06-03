import { EventType, RecordingEventType } from '~/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { IconFlag } from 'lib/lemon-ui/icons'

function StackTrace({}: { rawTrace: string }): JSX.Element | null {
    return null
}

export function ErrorDisplay({ event }: { event: EventType | RecordingEventType }): JSX.Element {
    if (event.event !== '$exception') {
        return <>Unknown type of error</>
    }

    const {
        $exception_type,
        $exception_message,
        $exception_stack_trace_raw,
        $lib,
        $lib_version,
        $browser,
        $browser_version,
        $os,
        $os_version,
        $active_feature_flags,
    } = event.properties
    return (
        <div className={'flex flex-col space-y-2'}>
            <h1 className={'mb-0'}>{$exception_message}</h1>
            <div className={'flex flex-row gap-2 flex-wrap'}>
                <LemonTag type={'caution'}>{$exception_type}</LemonTag>
                <LemonSnack color={'primary-highlight'}>
                    library: {$lib} {$lib_version}
                </LemonSnack>
                <LemonSnack color={'primary-highlight'}>
                    browser: {$browser} {$browser_version}
                </LemonSnack>
                <LemonSnack color={'primary-highlight'}>
                    OS: {$os} {$os_version}
                </LemonSnack>
            </div>
            <div className={'flex flex-col gap-1 mt-6'}>
                <h2 className={'text-sm'}>Active Feature Flags</h2>
                {$active_feature_flags && $active_feature_flags.length ? (
                    <div className={'flex flex-row gap-2 flex-wrap'}>
                        {$active_feature_flags.map((flag: string, index: number) => {
                            return (
                                <div
                                    key={index}
                                    className={'border rounded px-1.5 py-1 bg-primary-alt-highlight text-muted'}
                                >
                                    <IconFlag className={'pr-1'} />

                                    {flag}
                                </div>
                            )
                        })}
                    </div>
                ) : (
                    <div>No active feature flags</div>
                )}
            </div>
            <StackTrace rawTrace={$exception_stack_trace_raw} />
        </div>
    )
}
