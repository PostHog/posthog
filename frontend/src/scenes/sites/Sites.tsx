import { useValues } from 'kea'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { sitesLogic } from 'scenes/sites/sitesLogic'

export const Sites = (): JSX.Element => {
    const { siteStats, siteStatsLoading } = useValues(sitesLogic)
    return (
        <div className="flex flex-row flex-wrap py-2 px-4 gap-4">
            {siteStatsLoading && <Spinner />}
            {siteStats.map((s) => (
                <div key={s.site} className="border rounded px-2 py-1 flex flex-col gap2 items-center min-h-40">
                    <h2 className="m-0">{s.site}</h2>
                    <LemonDivider dashed={true} />
                    <div className="flex-1">
                        <pre>{JSON.stringify(s, null, 2)}</pre>
                    </div>
                </div>
            ))}
        </div>
    )
}
