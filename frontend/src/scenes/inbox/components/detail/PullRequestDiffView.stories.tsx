import { Meta, StoryObj } from '@storybook/react'

import { PullRequestDiffView } from './PullRequestDiffView'

type Story = StoryObj<typeof PullRequestDiffView>

const meta: Meta<typeof PullRequestDiffView> = {
    title: 'Scenes-App/Inbox/PullRequestDiffView',
    component: PullRequestDiffView,
    tags: ['autodocs'],
}
export default meta

const SAMPLE_DIFF = `diff --git a/frontend/src/lib/utils.ts b/frontend/src/lib/utils.ts
index 1234567..89abcde 100644
--- a/frontend/src/lib/utils.ts
+++ b/frontend/src/lib/utils.ts
@@ -1,6 +1,7 @@
 export function greet(name: string): string {
-    return 'Hello ' + name
+    // Friendlier greeting
+    return \`Hello, \${name}!\`
 }

 export const VERSION = '1.0.0'
diff --git a/README.md b/README.md
index 0000000..1111111 100644
--- a/README.md
+++ b/README.md
@@ -1,3 +1,3 @@
 # Project
-Old description.
+New description with more detail.

`

export const Default: Story = {
    args: {
        diff: SAMPLE_DIFF,
        truncated: false,
    },
}

export const Split: Story = {
    args: {
        diff: SAMPLE_DIFF,
        truncated: false,
        diffStyle: 'split',
    },
}

export const Truncated: Story = {
    args: {
        diff: SAMPLE_DIFF,
        truncated: true,
    },
}

export const Empty: Story = {
    args: {
        diff: '',
        truncated: false,
    },
}
