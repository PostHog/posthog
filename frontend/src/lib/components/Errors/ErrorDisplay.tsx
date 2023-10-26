import { EventType, RecordingEventType } from '~/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { IconFlag } from 'lib/lemon-ui/icons'
import clsx from 'clsx'
import { Link } from 'lib/lemon-ui/Link'
import posthog from 'posthog-js'

interface StackFrame {
    filename: string
    lineno: number
    colno: number
    function: string
}
function parseToFrames(rawTrace: string): StackFrame[] {
    return JSON.parse(rawTrace)
}

function StackTrace({ rawTrace }: { rawTrace: string }): JSX.Element | null {
    try {
        const frames = parseToFrames(rawTrace)
        return (
            <>
                {frames.length ? (
                    frames.map((frame, index) => {
                        const { filename, lineno, colno, function: functionName } = frame

                        return (
                            <TitledSnack
                                key={index}
                                title={functionName}
                                value={
                                    <>
                                        {filename}:{lineno}:{colno}
                                    </>
                                }
                            />
                        )
                    })
                ) : (
                    <LemonTag>Empty stack trace</LemonTag>
                )}
            </>
        )
    } catch (e: any) {
        //very meta
        posthog.capture('Cannot parse stack trace in Exception event', { tag: 'error-display-stack-trace', e })
        return <LemonTag type={'caution'}>Error parsing stack trace</LemonTag>
    }
}

function TitledSnack({
    title,
    value,
    type = 'default',
}: {
    title: string
    value: string | JSX.Element
    type?: 'default' | 'success'
}): JSX.Element {
    return (
        <div className={'flex flex-row items-center'}>
            <span
                className={clsx(
                    'pl-1.5 pr-1 py-1 max-w-full',
                    'border-r',
                    'rounded-l rounded-r-none',
                    'text-primary-alt overflow-hidden text-ellipsis',
                    type === 'success' ? 'bg-success-highlight' : 'bg-primary-highlight'
                )}
            >
                <strong>{title}:</strong>
            </span>
            <span
                className={clsx(
                    'pr-1.5 pl-1 py-1 max-w-full',
                    'rounded-r rounded-l-none',
                    'text-primary-alt overflow-hidden text-ellipsis',
                    type === 'success' ? 'bg-success-highlight' : 'bg-primary-highlight',
                    'flex flex-1 items-center'
                )}
            >
                {value}
            </span>
        </div>
    )
}

function ActiveFlags({ flags }: { flags: string[] }): JSX.Element {
    return (
        <>
            {flags && flags.length ? (
                <div className={'flex flex-row gap-2 flex-wrap'}>
                    {flags.map((flag, index) => {
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
        </>
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
        $sentry_url,
    } = event.properties
    return (
        <div className={'flex flex-col space-y-2 pr-4 pb-2'}>
            <h1 className={'mb-0 text-xl'}>{$exception_message}</h1>
            <div className={'flex flex-row gap-2 flex-wrap'}>
                <LemonTag type={'caution'}>{$exception_type}</LemonTag>
                <TitledSnack
                    type={'success'}
                    title={'captured by'}
                    value={
                        <>
                            {$sentry_url ? (
                                <Link
                                    className={'text-primary-alt hover:underline decoration-primary-alt cursor-pointer'}
                                    to={$sentry_url}
                                    target={'_blank'}
                                >
                                    Sentry
                                </Link>
                            ) : (
                                <>PostHog</>
                            )}
                        </>
                    }
                />
                <TitledSnack title={'synthetic'} value={$exception_synthetic ? 'true' : 'false'} />
                <TitledSnack title={'library'} value={`${$lib} ${$lib_version}`} />
                <TitledSnack title={'browser'} value={`${$browser} ${$browser_version}`} />
                <TitledSnack title={'os'} value={`${$os} ${$os_version}`} />
            </div>
            {!!$exception_stack_trace_raw?.length && (
                <div className={'flex flex-col gap-1 mt-6'}>
                    <h2>Stack Trace</h2>
                    <StackTrace rawTrace={$exception_stack_trace_raw} />
                </div>
            )}
            <div className={'flex flex-col gap-1 mt-6'}>
                <h2 className={'text-sm'}>Active Feature Flags</h2>
                <ActiveFlags flags={$active_feature_flags} />
            </div>
        </div>
    )
}
