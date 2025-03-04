import { IconGearFilled, IconHeadset } from '@posthog/icons'
import clsx from 'clsx'
import {
    IconAndroidOS,
    IconAppleIOS,
    IconBlackberry,
    IconChrome,
    IconDevices,
    IconFacebook,
    IconFirefox,
    IconInternetExplorer,
    IconLinux,
    IconMacOS,
    IconMicrosoftEdge,
    IconMonitor,
    IconOpera,
    IconPhone,
    IconSafari,
    IconSamsungInternet,
    IconTablet,
    IconUCBrowser,
    IconWeb,
    IconWindows,
} from 'lib/lemon-ui/icons'
import { forwardRef, HTMLAttributes, Ref } from 'react'
import { countryCodeToFlag } from 'scenes/insights/views/WorldMap'

const osIcons = {
    // backwards compatibility, Mac OS X is now macOS, we need to match both
    ['mac os x']: <IconMacOS />,
    ['macos']: <IconMacOS />,
    ['windows']: <IconWindows />,
    ['linux']: <IconLinux />,
    ['android']: <IconAndroidOS />,
    ['ios']: <IconAppleIOS />,
    ['other']: <IconGearFilled />,
    ['chrome os']: <IconChrome />,
    ['windows mobile']: <IconWindows />,
    ['windows phone']: <IconWindows />,
    ['xbox']: <IconWindows />,
    ['playstation']: <IconHeadset />,
    ['nintendo']: <IconHeadset />,
    ['blackberry']: <IconBlackberry />,
    ['watchos']: <IconMacOS />,
}

export const PROPERTIES_ICON_MAP = {
    $browser: {
        ['chrome']: <IconChrome />,
        ['chrome ios']: <IconChrome />,
        ['firefox']: <IconFirefox />,
        ['firefox ios']: <IconFirefox />,
        ['mozilla']: <IconFirefox />,
        ['safari']: <IconSafari />,
        ['mobile safari']: <IconSafari />,
        ['microsoft edge']: <IconMicrosoftEdge />,
        ['internet explorer']: <IconInternetExplorer />,
        ['internet explorer mobile']: <IconInternetExplorer />,
        ['opera']: <IconOpera />,
        ['opera mini']: <IconOpera />,
        ['android mobile']: <IconAndroidOS />,
        ['samsung internet']: <IconSamsungInternet />,
        ['facebook mobile']: <IconFacebook />,
        ['blackberry']: <IconBlackberry />,
        ['uc browser']: <IconUCBrowser />,
        ['konqueror']: <IconGearFilled />,
        ['other']: <IconWeb />,
    },
    $device_type: {
        ['desktop']: <IconMonitor />,
        ['mobile']: <IconPhone />,
        ['tablet']: <IconTablet />,
        ['console']: <IconHeadset />,
        ['wearable']: <IconDevices />,
        ['other']: <IconDevices />,
    },
    $os: osIcons,
    // some SDKs have $os_name instead of $os
    $os_name: osIcons,
    $geoip_country_code: {
        ['other']: <IconWeb />,
    },
}

interface PropertyIconProps {
    property: string
    value?: string
    className?: string
    onClick?: HTMLAttributes<HTMLDivElement>['onClick']
}

export const PropertyIcon = forwardRef(function PropertyIcon(
    { property, value, className }: PropertyIconProps,
    ref: Ref<HTMLDivElement>
): JSX.Element {
    if (!property || !(property in PROPERTIES_ICON_MAP)) {
        return <></>
    }

    const needle = value?.toLowerCase()
    let icon =
        !!needle && needle in PROPERTIES_ICON_MAP[property]
            ? PROPERTIES_ICON_MAP[property][needle]
            : PROPERTIES_ICON_MAP[property]['other']

    if (property === '$geoip_country_code' && value?.length === 2) {
        icon = countryCodeToFlag(value)
    }

    return (
        <div ref={ref} className={clsx('inline-flex items-center', className)}>
            {icon}
        </div>
    )
})
