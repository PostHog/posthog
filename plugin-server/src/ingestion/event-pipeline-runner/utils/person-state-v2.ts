/*
NOTES:
* Update is the entrypoint
* IF person processing is disabled:
  * We fetch the person via the read replica using the distinctId
  * IF no person is found:
    * We cache that we have inserted a row into `posthog_personlessdistinctid`
    * We insert the row into `posthog_personlessdistinctid`
    * If the insert returns "is_merged" as true, we refetch the person via the leader for some reason...
  * IF a person is found:   ^
    * We check if the event is within a minute of the person being created
    * If so we just return the person, not upgrading it 
    * (BUG?: I think we should process the person if force upgraded!)
  * FINALLY - we return the person or a fake person for that event
* IF person processing is enabled:
  * handleIdentifyOrAlias
    * Find the right ID depending on the event type
    * IF we have an ID to merge:
      *  IF the IDs are the same, we exit early
      *  IF either ID we are merging is illegal, we exit early
        * Also we capture an ingestion warning
      *  IF the ID we are merging is not illegal, we merge
        * We FETCH both persons 
        * IF either one doesnt exist
          * For the non existing person
          * We use a transaction and insert a personless to is_merged or set is_merged to true
          * If an insert took place then we also insert a distinctId row   
          * We return the existing person
        * ELSE if there are two existing persons with different IDs
          * We merge the persons
            * TODO
        * ELSE if we don't have any people
          * We create both personless distnctIds as merged
          * We get whichever personsless distinctId alreadxy existed if we can and use that as the primary distinctId
          * We create the person 
            * Insert into posthog_person
            * Insert each persondistinctid
        * FINALLY - we return the person
    * ELSE return
  * update the person (with shortcut if we already have the person)
    * get or create the person
    * IF not created:
      * If we know that it is identified (e.g. multiple distinctIds) then we set the is_identified flag
      * We modify the properties based on the event
        * We skip known events that we don't want to support like automated events
      * We do an update to the person modifying only the properties that should be set 
      * We publish to kafka
    * ELSE
      * We publish to kafka
*/

/**
 * NEW PLAN
 * I want to try and improve this whole thing by allowing us to batch everything up
 * I think we can do this by loading all data upfront (person_distinctid, person, personless_distinctid)
 * That way we know immediately if we need to do any merge work as well as what the case _should_ be for the inserted data
 * We would need to do a little bit of upfront work to parse all the possible IDs (alias, anon_distinct_id, distinct_id)
 *
 * Then the logic can be applied in a loop for all events, only writing persons at the very end in one big batch
 * Also we would want to modify the batching to make sure we catch all possible related merges together as one list
 *
 * For each batch:
 * * FETCH all the data we need
 * * for each event
 * * * If we need to "merge" then do so
 * * * * In the event where we are "creating" a value we use a placeholder person
 * * * Apply the property changes creating cloned person for the event
 * * * Keep track of the overall Persons including if they have modifications of some kind
 *
 * * FINALLY
 * * * Based on the modified Persons information we do the minimum number of DB calls to update the data
 * * * We only need to send one update per person, rather than many.
 * * * Do the DB calls to modify the Persons data as necessary
 * * * Loop over all the created event.person's and update them to have the correct person ID (that might have got created in the process)
 *
 */
