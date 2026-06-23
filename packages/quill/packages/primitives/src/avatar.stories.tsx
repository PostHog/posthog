import type { Meta, StoryObj } from '@storybook/react'
import { UserIcon } from 'lucide-react'

import { Avatar, AvatarFallback, AvatarGroup, AvatarImage } from './avatar'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from './tooltip'

const meta = {
    title: 'Primitives/Avatar',
    component: Avatar,
    tags: ['autodocs'],
} satisfies Meta<typeof Avatar>

export default meta
type Story = StoryObj<typeof meta>

// A few stable portraits + names for the image stories.
const MEMBERS = [
    { src: 'https://i.pravatar.cc/96?img=12', name: 'Ada Lovelace', initials: 'AL' },
    { src: 'https://i.pravatar.cc/96?img=32', name: 'Grace Hopper', initials: 'GH' },
    { src: 'https://i.pravatar.cc/96?img=45', name: 'Alan Turing', initials: 'AT' },
    { src: 'https://i.pravatar.cc/96?img=5', name: 'Katherine Johnson', initials: 'KJ' },
    { src: 'https://i.pravatar.cc/96?img=68', name: 'Edsger Dijkstra', initials: 'ED' },
]
const FACES = MEMBERS.map((m) => m.src)

export const Default: Story = {
    render: () => (
        <Avatar>
            <AvatarImage src={FACES[0]} alt="Ada Lovelace" />
            <AvatarFallback>AL</AvatarFallback>
        </Avatar>
    ),
} satisfies Story

// `size="xs"` (1.25rem) and `"sm"` (1.5rem) next to the default (2rem). The
// fallback text and any icon track the circle size automatically.
export const Sizes: Story = {
    render: () => (
        <div className="flex items-center gap-4">
            <Avatar size="xs">
                <AvatarImage src={FACES[1]} alt="Grace Hopper" />
                <AvatarFallback>GH</AvatarFallback>
            </Avatar>
            <Avatar size="sm">
                <AvatarImage src={FACES[1]} alt="Grace Hopper" />
                <AvatarFallback>GH</AvatarFallback>
            </Avatar>
            <Avatar size="default">
                <AvatarImage src={FACES[1]} alt="Grace Hopper" />
                <AvatarFallback>GH</AvatarFallback>
            </Avatar>
        </div>
    ),
} satisfies Story

// Fallbacks render when there's no image: initials, or a bare lucide icon (sized
// to ~60% of the circle by the component, so don't add a `size-*` class).
export const Fallback: Story = {
    render: () => (
        <div className="flex items-center gap-4">
            <Avatar>
                <AvatarFallback>JS</AvatarFallback>
            </Avatar>
            <Avatar>
                <AvatarFallback>
                    <UserIcon />
                </AvatarFallback>
            </Avatar>
            <Avatar size="sm">
                <AvatarFallback>
                    <UserIcon />
                </AvatarFallback>
            </Avatar>
        </div>
    ),
} satisfies Story

// A broken `src` falls back to the initials. (Base UI swaps to the fallback once
// the image errors.)
export const BrokenImage: Story = {
    render: () => (
        <Avatar>
            <AvatarImage src="https://example.com/does-not-exist.png" alt="Missing" />
            <AvatarFallback>MK</AvatarFallback>
        </Avatar>
    ),
} satisfies Story

// AvatarGroup, inline (default): a simple gapped row.
export const Group: Story = {
    render: () => (
        <AvatarGroup>
            {FACES.slice(0, 4).map((src, i) => (
                <Avatar key={src}>
                    <AvatarImage src={src} alt={`Member ${i + 1}`} />
                    <AvatarFallback>M{i + 1}</AvatarFallback>
                </Avatar>
            ))}
        </AvatarGroup>
    ),
} satisfies Story

// `stacked` overlaps the avatars. Hover (or focus) the group: they spread back to
// the inline gap via a pure `transform`, so the surrounding layout never reflows —
// the avatars slide out over the space to their right.
export const GroupStacked: Story = {
    render: () => (
        <div className="flex items-center gap-4">
            <span>Team</span>
            <AvatarGroup stacked>
                {FACES.map((src, i) => (
                    <Avatar key={src}>
                        <AvatarImage src={src} alt={`Member ${i + 1}`} />
                        <AvatarFallback>M{i + 1}</AvatarFallback>
                    </Avatar>
                ))}
            </AvatarGroup>
            <span>(hover the avatars)</span>
        </div>
    ),
} satisfies Story

// Same layout as GroupStacked, but `reverse` anchors the pile to its right edge
// and spreads left on hover — so the avatars slide out over the "Team" label to
// their left instead of the text on their right. The rightmost avatar sits on top.
export const GroupStackedReverse: Story = {
    render: () => (
        <div className="flex items-center gap-4">
            <span>Team</span>
            <AvatarGroup stacked reverse>
                {FACES.map((src, i) => (
                    <Avatar key={src}>
                        <AvatarImage src={src} alt={`Member ${i + 1}`} />
                        <AvatarFallback>M{i + 1}</AvatarFallback>
                    </Avatar>
                ))}
            </AvatarGroup>
            <span>(hover the avatars)</span>
        </div>
    ),
} satisfies Story

// A stacked group led by an overflow count (styled fallback). It sits first, so —
// with the default leftmost-on-top stacking — it reads in front of the faces; on
// hover the whole pile spreads.
export const GroupStackedWithCount: Story = {
    render: () => (
        <AvatarGroup stacked>
            <Avatar>
                <AvatarFallback className="bg-primary/15 text-primary normal-case">+3</AvatarFallback>
            </Avatar>
            {FACES.slice(0, 3).map((src, i) => (
                <Avatar key={src}>
                    <AvatarImage src={src} alt={`Member ${i + 1}`} />
                    <AvatarFallback>M{i + 1}</AvatarFallback>
                </Avatar>
            ))}
        </AvatarGroup>
    ),
} satisfies Story

// `size` on the group forwards to every Avatar child and tightens the stacked
// overlap to match the smaller circles.
export const GroupStackedSmall: Story = {
    render: () => (
        <AvatarGroup stacked size="sm">
            {FACES.map((src, i) => (
                <Avatar key={src}>
                    <AvatarImage src={src} alt={`Member ${i + 1}`} />
                    <AvatarFallback>M{i + 1}</AvatarFallback>
                </Avatar>
            ))}
        </AvatarGroup>
    ),
} satisfies Story

// Inline group where each avatar is a tooltip trigger. Wrap the group (or the app)
// in a single TooltipProvider. The Avatar is the trigger via `render`, so it stays
// hoverable and focusable.
export const GroupWithTooltips: Story = {
    render: () => (
        <TooltipProvider>
            <AvatarGroup>
                {MEMBERS.slice(0, 4).map((m) => (
                    <Tooltip key={m.src}>
                        <TooltipTrigger
                            render={
                                <Avatar>
                                    <AvatarImage src={m.src} alt={m.name} />
                                    <AvatarFallback>{m.initials}</AvatarFallback>
                                </Avatar>
                            }
                        />
                        <TooltipContent>{m.name}</TooltipContent>
                    </Tooltip>
                ))}
            </AvatarGroup>
        </TooltipProvider>
    ),
} satisfies Story

// Same, stacked: hovering an avatar both spreads the pile and shows its tooltip.
// The tooltip delay matches the 200ms spread duration, so it appears once the
// avatars have finished expanding rather than over a still-moving pile.
export const GroupStackedWithTooltips: Story = {
    render: () => (
        <TooltipProvider delay={200}>
            <AvatarGroup stacked>
                {MEMBERS.map((m) => (
                    <Tooltip key={m.src}>
                        <TooltipTrigger
                            render={
                                <Avatar>
                                    <AvatarImage src={m.src} alt={m.name} />
                                    <AvatarFallback>{m.initials}</AvatarFallback>
                                </Avatar>
                            }
                        />
                        <TooltipContent>{m.name}</TooltipContent>
                    </Tooltip>
                ))}
            </AvatarGroup>
        </TooltipProvider>
    ),
} satisfies Story

// Each avatar links to its member: `render` makes the Avatar's root an anchor, so
// every one is focusable (keyboard focus also triggers the stacked spread via
// `:focus-within`).
export const GroupStackedWithLinks: Story = {
    render: () => (
        <AvatarGroup stacked>
            {MEMBERS.map((m) => (
                <Avatar
                    key={m.src}
                    render={
                        // eslint-disable-next-line react/forbid-elements
                        <a
                            href={`https://posthog.com/${m.initials.toLowerCase()}`}
                            target="_blank"
                            rel="noreferrer"
                            aria-label={m.name}
                        />
                    }
                >
                    <AvatarImage src={m.src} alt={m.name} />
                    <AvatarFallback>{m.initials}</AvatarFallback>
                </Avatar>
            ))}
        </AvatarGroup>
    ),
} satisfies Story
