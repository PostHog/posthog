import React from 'react'

export function VerifiedDomains(): JSX.Element {
    return (
        <div>
            <div id="domain-whitelist" /> {/** For backwards link compatibility. Remove after 6/1/22. */}
            <h2 id="verified-domains" className="subtitle">
                Verified domains
            </h2>
        </div>
    )
}
