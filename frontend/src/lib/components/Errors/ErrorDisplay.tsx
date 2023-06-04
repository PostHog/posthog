import { EventType, RecordingEventType } from '~/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { IconFlag } from 'lib/lemon-ui/icons'
import clsx from 'clsx'

function StackTrace({}: { rawTrace: string }): JSX.Element | null {
    return null
}

function TitledSnack({ title, value }: { title: string; value: string }): JSX.Element {
    return (
        <div className={'flex flex-row items-center'}>
            <span
                className={clsx(
                    'pl-1.5 pr-1 py-1 max-w-full',
                    'border-r',
                    'rounded-l rounded-r-none',
                    'text-primary-alt overflow-hidden text-ellipsis bg-primary-highlight',
                    'inline-flex items-center'
                )}
            >
                <strong>{title}:</strong>
            </span>
            <span
                className={clsx(
                    'pr-1.5 pl-1 py-1 max-w-full',
                    'rounded-r rounded-l-none',
                    'text-primary-alt overflow-hidden text-ellipsis bg-primary-highlight',
                    'inline-flex items-center'
                )}
            >
                {value}
            </span>
        </div>
    )
}

export function ErrorDisplay({ event }: { event: EventType | RecordingEventType }): JSX.Element {
    if (event.event !== '$exception') {
        return <>Unknown type of error</>
    }

    const {
        $exception_type,
        $exception_message,
        $exception_stack_trace_raw,
        $exception_synthetic,
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
                <TitledSnack title={'synthetic'} value={$exception_synthetic ? 'true' : 'false'} />
                <TitledSnack title={'library'} value={`${$lib} ${$lib_version}`} />
                <TitledSnack title={'browser'} value={`${$browser} ${$browser_version}`} />
                <TitledSnack title={'os'} value={`${$os} ${$os_version}`} />
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
