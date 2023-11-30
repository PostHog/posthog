import { LemonButton } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'

import { Spinner as Spinner, SpinnerOverlay } from './Spinner'

const meta: Meta<typeof Spinner> = {
    title: 'Lemon UI/Spinner',
    component: Spinner,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
    tags: ['autodocs'],
}
export default meta

export function Default(): JSX.Element {
    return <Spinner />
}

export function Sizes(): JSX.Element {
    return (
        <div className="space-y-2">
            <p>
                Spinners will inherit their size based on fontSize making it easy to style with CSS or utility classes
            </p>

            <div className="flex items-center gap-2 text-xs">
                <Spinner />
                <span>text-sm</span>
            </div>
            <div className="flex items-center gap-2">
                <Spinner />
                <span>Default</span>
            </div>

            <div className="flex items-center gap-2 text-xl">
                <Spinner />
                <span>text-xl</span>
            </div>

            <div className="flex items-center gap-2 text-5xl">
                <Spinner />
                <span>text-5xl</span>
            </div>
        </div>
    )
}

export function TextColored(): JSX.Element {
    return (
        <div className="bg-default p-4 text-4xl">
            <Spinner textColored className="text-white" />
        </div>
    )
}

export function InButtons(): JSX.Element {
    return (
        <div className="flex gap-2 items-center">
            <LemonButton type="primary" loading>
                Primary
            </LemonButton>
            <LemonButton type="secondary" loading>
                Secondary Button
            </LemonButton>

            <LemonButton type="secondary" status="danger" loading>
                Secondary Danger
            </LemonButton>
        </div>
    )
}

export function AsOverlay(): JSX.Element {
    return (
        <div className="relative">
            <h1>Hey there</h1>
            <p>
                Illum impedit eligendi minima aperiam. Quo aut eaque debitis dolor corrupti fugit sit qui. Esse
                quibusdam doloremque beatae animi fugit maiores. Nemo totam aliquid similique. Autem labore deleniti eum
                qui fugiat nam fugiat inventore. Praesentium dolores neque nobis. Et blanditiis consequatur corporis
                quis. Sint eligendi tempore nostrum ullam deserunt aspernatur. Enim quod laboriosam provident odio est
                suscipit. Aspernatur voluptas dolor quia recusandae alias incidunt. Et neque officiis quas. Fugiat
                quisquam harum ab porro. Sit in totam aut tempora dolor ut blanditiis facilis. Maiores sed expedita
                ipsam ut. Cupiditate animi quisquam sequi corrupti hic ea mollitia vero. Aspernatur sed ut in non
                perferendis. Ut natus quia illum dignissimos suscipit repudiandae iure debitis. Cupiditate deserunt
                ratione odio vel. Ducimus et iure voluptatem ut ut aspernatur dolor. Iure voluptatem tempora ullam est
                ex laudantium. Sunt tempore molestiae voluptas dolores et ducimus. Quia et provident qui et ut magni.
                Tenetur sed quae culpa.
            </p>

            <SpinnerOverlay />
        </div>
    )
}
