import { BuilderHog3 } from 'lib/components/hedgehogs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

export function UsageBanner(): JSX.Element {
    return (
        <LemonBanner type="info" hideIcon className="overflow-visible">
            <div className="flex items-center gap-4">
                <div className="relative flex-shrink-0 mr-2">
                    <LemonTag type="completion" className="absolute top-2.5 left-0 transform -rotate-12">
                        EARLY ACCESS
                    </LemonTag>
                    <BuilderHog3 className="w-20 h-20 mt-5" />
                </div>
                <div className="text-primary">
                    <p>
                        We're still working on these dashboards, and we'd love to hear your feedback! A couple of things
                        to keep in mind:
                    </p>
                    <ul className="list-disc list-inside pl-2">
                        <li>
                            Product usage is reported on a daily basis (UTC), so figures for a given day are available
                            on the following day
                        </li>
                        <li>Some product add-ons are not included here yet (e.g. data pipelines)</li>
                    </ul>
                </div>
            </div>
        </LemonBanner>
    )
}
