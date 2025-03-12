# @posthog/icons

<img width="1403" alt="image" src="https://github.com/user-attachments/assets/54131c59-4294-4078-9ff0-751bae88deb0" />

## Install

The `@posthog/icons` pacakge is built and installed as part of pnpm workspaces by turbo.

## Usage

```jsx
import { Logomark } from '@posthog/icons'

const Example = () => {
    return <Logomark />
}
```

## Development

`yarn dev`

## Publishing to NPM

We use the package as part of a workspace, however if there's a need to share an updated set of icons with the wider world, feel free to bump the version and publish it on npm.

## Requesting icons

1. If you see an appropriate icon, use that first
1. Check the [Central Icons Figma file](https://www.figma.com/file/5vlhJx4BrYePkBaq1bZ0Ci/central-icon-system-v1.15---latest?type=design&node-id=7-118&mode=design&t=0A5eHFpLAHbhTLLv-0) to see if there is anything appropriate (stroke: 1.5, radius: 1.0) and add it to the package. If possible, please:
    1. Convert strokes to outlines in Figma (break apart, select icon, Path → Outline stroke)
    1. Optimize with [SVGOMG](https://jakearchibald.github.io/svgomg/)
    1. When pasting into `Icons.tsx`, locate where the icon should go _alphabetically_
    1. After pasting, remove any fills and convert `fill-rule` and `clip-rule` to `fillRule` and `clipRule`
1. Create an issue in this repo so Cory can add the same icon to our [Figma icon library](https://www.figma.com/file/fIXZa0PCGX1oBwQm0sOT7s/Icons?type=design&node-id=0%3A1&mode=design&t=I6lG9OdvUp3ZRt9I-1)
1. React out to Cory if there is something you would like but can't find
