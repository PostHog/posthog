import { IconJavascript, IconNodeJS, IconPython, LemonIconProps } from 'lib/lemon-ui/icons'
import { match } from 'ts-pattern'

import { Runtime } from '../utils'

export function RuntimeIcon({ runtime, ...props }: { runtime?: Runtime } & LemonIconProps): JSX.Element {
    return match(runtime)
        .with('python', () => <IconPython {...props} />)
        .with('web', () => <IconJavascript {...props} />)
        .with('node', () => <IconNodeJS {...props} />)
        .otherwise(() => <></>)
}
