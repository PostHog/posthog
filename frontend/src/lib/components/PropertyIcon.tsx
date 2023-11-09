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
} from 'lib/lemon-ui/icons'
import clsx from 'clsx'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { countryCodeToFlag } from 'scenes/insights/views/WorldMap'
import { HTMLAttributes, ReactNode } from 'react'

export const PROPERTIES_ICON_MAP = {
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
    $geoip_country_code: {
        ['Other']: <IconWeb />,
    },
}

interface PropertyIconProps {
    property: string
    value?: string
    className?: string
    noTooltip?: boolean
    onClick?: HTMLAttributes<HTMLDivElement>['onClick']
    tooltipTitle?: (property: string, value?: string) => ReactNode // Tooltip title will default to `value`
}

export function PropertyIcon({
    property,
    value,
    className,
    noTooltip,
    tooltipTitle,
    onClick,
}: PropertyIconProps): JSX.Element {
    if (!property || !(property in PROPERTIES_ICON_MAP)) {
        return <></>
    }

    let icon =
        !!value && value in PROPERTIES_ICON_MAP[property]
            ? PROPERTIES_ICON_MAP[property][value]
            : PROPERTIES_ICON_MAP[property]['Other']

    if (property === '$geoip_country_code' && value?.length === 2) {
        icon = countryCodeToFlag(value)
    }

    const content = (
        <div onClick={onClick} className={clsx('inline-flex items-center', className)}>
            {icon}
        </div>
    )

    return noTooltip ? content : <Tooltip title={tooltipTitle?.(property, value) ?? value}>{content}</Tooltip>
}
