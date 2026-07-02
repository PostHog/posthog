from .matrix import HedgeboxMatrix

# This is a simulation of an online drive SaaS called Hedgebox
# See this RFC for the reasoning behind it:
# https://github.com/PostHog/product-internal/blob/main/requests-for-comments/2022-03-23-great-demo-data.md

# Simulation features:
# - the product is used by lots of personal users, but businesses bring the most revenue
# - most users are from the US, but there are blips all over the world
# - timezones are accurate on the country level
# - usage times are accurate taking into account time of day, timezone, and user profile (personal or business)
# - Hedgebox is sponsoring the well-known YouTube channel about technology Marius Tech Tips - there's a landing page
# - an experiment with a new signup page is running, and it's showing positive results
# - Internet Explorer users do worse

# See this flowchart for the layout of the product:
# https://www.figma.com/file/nmvylkFx4JdTRDqyo5Vkb5/Hedgebox-Paths

__all__ = ["HedgeboxMatrix"]
