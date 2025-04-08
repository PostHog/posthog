import { IconJavascript, IconNodeJS, IconPython, LemonIconProps } from 'lib/lemon-ui/icons'
import { createElement } from 'react'

const libAssets = {
    'posthog-python': {
        icon: IconPython,
        name: 'Python',
    },
    web: {
        icon: IconJavascript,
        name: 'Web',
    },
    'posthog-node': {
        icon: IconNodeJS,
        name: 'NodeJs',
    },
}

export function LibIcon({ lib, ...props }: { lib: string } & LemonIconProps): JSX.Element {
    switch (lib) {
        case 'posthog-python':
        case 'web':
        case 'posthog-node':
            return createElement(libAssets[lib].icon, props)
        default:
            return <span />
    }
}
