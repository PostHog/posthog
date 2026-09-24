import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

type ProjectsLoadErrorProps = {
    onReload?: () => void
}

export const ProjectsLoadError = ({ onReload }: ProjectsLoadErrorProps): JSX.Element => (
    <LemonBanner type="error" action={onReload ? { children: 'Try again', onClick: onReload } : undefined}>
        Couldn't load your projects.
    </LemonBanner>
)
