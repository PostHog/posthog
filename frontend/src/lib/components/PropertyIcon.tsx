import {
    IconAndroidOS,
    IconAppleIOS,
    IconChrome,
    IconCogBox,
    IconDevices,
    IconFirefox,
    IconInternetExplorer,
    IconLinux,
    IconMacOS,
    IconMicrosoftEdge,
    IconMonitor,
    IconOpera,
    IconPhone,
    IconSafari,
    IconTablet,
    IconWeb,
    IconWindows,
} from 'lib/components/icons'
import clsx from 'clsx'

const PROPERTIES_ICON_MAP = {
    $browser: {
        ['Chrome']: <IconChrome />,
        ['Chrome iOS']: <IconChrome />,
        ['Firefox']: <IconFirefox />,
        ['Firefox iOS']: <IconFirefox />,
        ['Mozilla']: <IconFirefox />,
        ['Safari']: <IconSafari />,
        ['Mobile Safari']: <IconSafari />,
        ['Microsoft Edge']: <IconMicrosoftEdge />,
        ['Internet Explorer']: <IconInternetExplorer />,
        ['Opera']: <IconOpera />,
        ['Opera Mini']: <IconOpera />,
        ['Other']: <IconWeb />,
    },
    $device_type: {
        ['Desktop']: <IconMonitor />,
        ['Mobile']: <IconPhone />,
        ['Tablet']: <IconTablet />,
        ['Other']: <IconDevices />,
    },
    $os: {
        ['Mac OS X']: <IconMacOS />,
        ['Windows']: <IconWindows />,
        ['Linux']: <IconLinux />,
        ['Android']: <IconAndroidOS />,
        ['iOS']: <IconAppleIOS />,
        ['Other']: <IconCogBox />,
    },
}

interface PropertyIconProps {
    property: string
    value?: string
    hideIcon?: boolean
    hideText?: boolean
    className?: string
}

export function PropertyIcon({
    property,
    value,
    className,
    hideIcon = false,
    hideText = false,
}: PropertyIconProps): JSX.Element {
    if (!property || !(property in PROPERTIES_ICON_MAP)) {
        return <span>{!hideText && value}</span>
    }

    const icon =
        !!value && value in PROPERTIES_ICON_MAP[property]
            ? PROPERTIES_ICON_MAP[property][value]
            : PROPERTIES_ICON_MAP[property]['Other']
    return (
        <span className={clsx('inline-flex items-center gap-1 whitespace-nowrap flex-nowrap', className)}>
            {!hideIcon && <span className="flex items-center text-base">{icon}</span>}
            {!hideText && <span>{value}</span>}
        </span>
    )
}
