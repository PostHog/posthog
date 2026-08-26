# Product empty-state layout

`ProductEmptyState` responds to the width of its scene container, including the space left after the sidebar and side panel.

- Below 64rem, the preview stacks below the setup copy and stays visible.
- At 64rem and above, the preview occupies a separate column.
- A `beside` hedgehog appears beside the copy when the copy container reaches 52rem. Below that, a smaller illustration appears above the product name.
- Secondary links and replay vision preview filters wrap when space is limited.

Use `containerWidth` in `productEmptyStateStory` to cover narrow scenes independently of the Storybook viewport. Cover both setup and waiting modes when the product supports them.
