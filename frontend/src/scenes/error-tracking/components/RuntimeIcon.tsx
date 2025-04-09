import { ErrorTrackingRuntime } from 'lib/components/Errors/types'
import { IconJavascript, IconNodeJS, IconPython, LemonIconProps } from 'lib/lemon-ui/icons'
import { match } from 'ts-pattern'

export function RuntimeIcon({ runtime, ...props }: { runtime?: ErrorTrackingRuntime } & LemonIconProps): JSX.Element {
    return match(runtime)
        .with('python', () => <IconPython {...props} />)
        .with('web', () => <IconJavascript {...props} />)
        .with('node', () => <IconNodeJS {...props} />)
        .otherwise(() => <></>)
}
