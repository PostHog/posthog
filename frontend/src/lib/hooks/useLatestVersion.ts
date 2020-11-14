// DEPRECATED: this logic is now found in navigationLogic.ts

import { useState, useEffect } from 'react'
import api from 'lib/api'

interface Version {
    version: string
}

export function useLatestVersion(...dependencies: any[]): Version['version'] | null {
    const [latestVersion, setLatestVersion] = useState<Version['version'] | null>(null)

    useEffect(() => {
        api.get('https://update.posthog.com/versions').then((versions: Version[]) => {
            setLatestVersion(versions[0]['version'])
        })
    }, dependencies ?? [])

    return latestVersion
}
