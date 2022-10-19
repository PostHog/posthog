import { Tooltip } from 'lib/components/Tooltip'
import { countryCodeToFlag } from 'scenes/insights/views/WorldMap/countryCodes'
import { PersonType } from '~/types'

export type PlayerPersonSummaryProps = {
    person?: PersonType
}

const PropertiesIconMap = {
    $os: {
        'Mac OS X': '🍎',
    },
    $browser: {
        Chrome: '🌐',
        Firefox: '🦊',
    },
    $geoip_country_code: countryCodeToFlag,
}

export function PlayerPersonSummary({ person }: PlayerPersonSummaryProps): JSX.Element | null {
    if (!person) {
        return null
    }

    return (
        <span className="text-lg space-x-1">
            {Object.keys(PropertiesIconMap).map((x) => {
                const content =
                    typeof PropertiesIconMap[x] === 'function'
                        ? PropertiesIconMap[x](person.properties[x])
                        : PropertiesIconMap[x]?.[person.properties[x]]

                return content ? (
                    <Tooltip title={person.properties[x]}>
                        <span key={x}>{content}</span>
                    </Tooltip>
                ) : null
            })}
        </span>
    )
}
