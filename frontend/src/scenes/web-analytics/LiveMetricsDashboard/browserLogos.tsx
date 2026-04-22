import React from 'react'

import { IconWeb } from 'lib/lemon-ui/icons'

import chromeSvg from 'public/browser_logos/chrome.svg'
import edgeSvg from 'public/browser_logos/edge.svg'
import firefoxSvg from 'public/browser_logos/firefox.svg'
import operaSvg from 'public/browser_logos/opera.svg'
import safariIosSvg from 'public/browser_logos/safari-ios.svg'
import safariSvg from 'public/browser_logos/safari.svg'
import samsungInternetSvg from 'public/browser_logos/samsung-internet.svg'

interface BrowserLogoProps {
    className?: string
}

const BROWSER_LOGOS: Record<string, { src: string; alt: string }> = {
    chrome: { src: chromeSvg, alt: 'Chrome' },
    'chrome ios': { src: chromeSvg, alt: 'Chrome' },
    chromium: { src: chromeSvg, alt: 'Chrome' },
    firefox: { src: firefoxSvg, alt: 'Firefox' },
    'firefox ios': { src: firefoxSvg, alt: 'Firefox' },
    mozilla: { src: firefoxSvg, alt: 'Firefox' },
    safari: { src: safariSvg, alt: 'Safari' },
    'safari ios': { src: safariIosSvg, alt: 'Safari iOS' },
    'mobile safari': { src: safariIosSvg, alt: 'Safari' },
    edge: { src: edgeSvg, alt: 'Edge' },
    'microsoft edge': { src: edgeSvg, alt: 'Edge' },
    opera: { src: operaSvg, alt: 'Opera' },
    'opera mini': { src: operaSvg, alt: 'Opera' },
    'samsung internet': { src: samsungInternetSvg, alt: 'Samsung Internet' },
}

const BrowserLogoCache = new Map<string, React.ComponentType<BrowserLogoProps>>()
for (const [key, logo] of Object.entries(BROWSER_LOGOS)) {
    const Component = ({ className }: BrowserLogoProps): JSX.Element => (
        <img src={logo.src} alt={logo.alt} className={className} />
    )
    Component.displayName = `BrowserLogo_${logo.alt}`
    BrowserLogoCache.set(key, Component)
}

const FallbackBrowserLogo = ({ className }: BrowserLogoProps): JSX.Element => <IconWeb className={className} />

export const getBrowserLogo = (browserName: string | undefined): React.ComponentType<BrowserLogoProps> =>
    BrowserLogoCache.get(browserName?.toLowerCase() ?? '') ?? FallbackBrowserLogo
