"""
Contract types for data_catalog.

Frozen dataclasses that define what this product exposes to other products. No Django imports.

######################################################################################
#                                                                                    #
#   DO NOT COPY THIS FILE, OR facade/api.py, INTO A NEW PRODUCT.                     #
#   This product does NOT implement the facade pattern correctly.                    #
#                                                                                    #
#   The reasoning below - "no in-process cross-product consumers, so no contracts    #
#   are needed yet" - is the exact test products/architecture.md calls WRONG:        #
#                                                                                    #
#       "'no in-process callers, so we don't need a facade' is the wrong test:       #
#        a product whose only consumers are over HTTP is *not* facade-optional -     #
#        there the facade's whole job is sealing its own presentation."              #
#                                                                                    #
#   Consequences, both real today:                                                   #
#     - facade/api.py re-exports logic functions and ORM classes instead of          #
#       accepting and returning frozen dataclasses, so callers hold live models.     #
#     - `hogli product:lint data_catalog` withholds backend:contract-check. This     #
#       product is NOT isolated and pays the full Django suite until it is fixed.    #
#                                                                                    #
#   Correct examples: products/visual_review, products/tasks, products/error_tracking#
#                                                                                    #
######################################################################################

Contracts will land here when this product's facade converts models to frozen dataclasses.
Until then, ``facade.models`` re-exports the ORM classes that information_schema loaders and
this product's own presentation layer read directly.
"""
