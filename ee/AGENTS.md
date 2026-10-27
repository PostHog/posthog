# Enterprise edition code

Do not add new features to the `ee/` folder under any circumstance. Only extend existing code under the `ee/` folder when absolutely necessary, and the code cannot be placed under the `posthog/` directory or one of the `product/*` directories. The `ee/` folder is deprecated, and our goal is to move as much code out of it as possible. If you absolutely must add new code to the `ee/` folder, explicitly state why in your pull request description.
