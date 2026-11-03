import { useState } from 'react'

export function ConnectedAppLogo({ name, logoUri }: { name: string; logoUri: string | null }): JSX.Element {
    // A CIMD app without a logo of its own gets its host's touch icon, which may not exist
    const [logoFailed, setLogoFailed] = useState(false)

    if (logoUri && !logoFailed) {
        return (
            <div className="w-8 h-8 shrink-0 rounded bg-bg-light border flex items-center justify-center p-1">
                <img
                    src={logoUri}
                    alt={`${name} logo`}
                    className="w-full h-full object-contain"
                    onError={() => setLogoFailed(true)}
                />
            </div>
        )
    }
    return (
        <div className="w-8 h-8 shrink-0 rounded bg-border flex items-center justify-center text-sm font-bold text-muted">
            {name.charAt(0).toUpperCase()}
        </div>
    )
}
