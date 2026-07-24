import { SceneContent } from '~/layout/scenes/components/SceneContent'

// Capped and centered like onboarding's product selection: full-width reads stretched
// and empty on large monitors, a ~72rem column keeps the page dense
export function QuickstartPageShell({ children }: { children: React.ReactNode }): JSX.Element {
    return <SceneContent className="gap-y-8 py-4 w-full max-w-6xl mx-auto">{children}</SceneContent>
}
