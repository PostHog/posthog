import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

export const DataWarehousePricingNotice = (): JSX.Element => {
    return (
        <LemonBanner type="info" className="my-4">
            <div className="flex items-center flex-wrap gap-2 justify-between">
                <div className="flex-1 min-w-full sm:min-w-0">
                    PostHog Data Warehouse is in Beta. Thanks for taking part! We want to outline how pricing will work
                    for those interested in trying out the Beta. As of now it's free to use, but we will introduce
                    pricing in the near future. Details here:
                </div>
            </div>
        </LemonBanner>
    )
}
