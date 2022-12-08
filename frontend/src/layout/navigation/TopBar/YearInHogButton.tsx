import { HeartHog } from 'lib/components/hedgehogs'
import { LemonButton } from 'lib/components/LemonButton'

export function YearInHogButton({ url }: { url: string | null }): JSX.Element | null {
    return url ? (
        <div className={'relative'}>
            <HeartHog width={'36'} height={'36'} className={'CheekyHog'} />

            <LemonButton type={'primary'} status={'primary'} to={url} targetBlank={true} size={'small'}>
                My year in PostHog
            </LemonButton>
        </div>
    ) : null
}
