"""Reads a platform verdict and the verdict a source's own stack produced for the same check,
and says whether they agree.

Every source adopts the platform by evaluating in parallel while the product's own stack keeps
notifying. That posture is only worth its query cost if something reads both verdicts. This
package is that reader and its classifier. The contract a source implements to supply its own half
is in `facade.contracts`.
"""
